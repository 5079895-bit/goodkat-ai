import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import database
import ai

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
INVITE_CODE = os.getenv("INVITE_CODE", "1234")

if not TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. Положи токен от BotFather в файл .env: BOT_TOKEN=123456:ABC...")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

if INVITE_CODE == "1234":
    logger.warning("INVITE_CODE не задан в .env — вход открыт по стандартному коду 1234")

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

_user_locks: dict[int, asyncio.Lock] = {}
_help_mode: set[int] = set()
_help_waiting_answer: set[int] = set()
_pending_clarification: dict[int, dict] = {}
_pending_week_end: set[int] = set()
_pending_weekly_weight: set[int] = set()
_pending_agree: set[int] = set()

# ПЕРЕМЕННЫЕ ДЛЯ МЕНЮ
_pending_menu_mode: dict[int, dict] = {}
_active_menu: dict[int, dict] = {}

# ПЕРЕМЕННЫЕ ДЛЯ ФОТО НАПИТКОВ
_pending_water: set[int] = set()
_evening: dict[int, dict] = {}

_no_guilt_shown_today: dict[int, str] = {}

BTN_EAT = "🍽 ЗАПИСАТЬ ЕДУ"
BTN_SUMMARY = "⏰ ИТОГ ДНЯ"
BTN_HELP = "🐾 КОТИК, ПОДСКАЖИ"
BTN_MENU = "✨ ЗАЙТИ КРАСИВО"
BTN_WATER = "💧 ВОДА"
BTN_KOTIK = "🐾 КОТИК РЯДОМ"
BTN_MENU_SEARCH = "🐾 ПОИЩЕМ ПО МЕНЮ"
BTN_EAT_OUT = "🐾 ПОЕДИМ НЕ ДОМА"
BTN_EVENING = "🥂 ТЁПЛЫЙ ВЕЧЕР С БОКАЛОМ"
BTN_BACK = "⬅️ Назад"
BTN_CONTINUE = "➡️ Продолжаем?"
BTN_AGREE = "✅ Согласна / Согласен"
BTN_HELP_YES = "🐾 Да"
BTN_HELP_NO = "😺 Нет"

# Маркеры, по которым понимаем, что ИИ не уверен в напитке
_CONTROL_BUTTONS = (
    BTN_EAT, BTN_HELP, BTN_SUMMARY, BTN_MENU, BTN_WATER,
    BTN_KOTIK, BTN_MENU_SEARCH, BTN_EAT_OUT, BTN_EVENING, BTN_BACK, BTN_CONTINUE,
)


DIARY_HELP_TEXT = (
    "📝 <b>Как вести дневник (это просто!)</b>\n\n"
    "Пиши, что съел и выпил, — как вспомнится. Точность до грамма не нужна:\n"
    "🍲 Борщ с мясом и сметаной 300 г — отлично!\n"
    "🍗 Жареная куриная котлета 100 г и картофельное пюре на молоке 3,2% — прекрасно!\n\n"
    "Можно и покороче:\n"
    "🍎 Яблоко, одно среднее (или 150 г)\n"
    "🥛 Кефир 2,5%, стакан\n"
    "💧 Вода 300 мл (воду просто напиши текстом — кнопка не нужна)\n"
    "☕ Кофе с молоком, без сахара\n\n"
    "А если вес не знаешь — просто скажи «не знаю». Я возьму средний показатель и всё запишу, без лишних вопросов. 💚\n\n"
    "Что-то забыл — не беда, записывай по ходу дня, как удобно.\n\n"
    "📷 Мы только учимся распознавать еду по фото. Если что-то не пойму — уточню, без переживаний."
)
DIARY_HELP_TAIL = "Расскажи, пожалуйста, что ты сегодня уже ел и пил. Поехали! 💚"

EVENING_INTRO = (
    "🥂 <b>Хорошего вечера!</b>\n\n"
    "Я рядом и не буду считать каждый глоток. Одно напутствие, и больше не пристаю: "
    "чередуй бокал с водой — утром скажешь себе спасибо.\n\n"
    "Дальше просто записывай, что съел и выпил. Без нравоучений и без «а точно ли тебе надо». 💚"
)
EVENING_TOUCHES = (
    "Кстати, стакан воды между бокалами правда помогает утру быть добрее. 💚",
    "Ты хорошо держишь баланс — наслаждайся вечером, я не мешаю. 🐾",
)
EVENING_BYE = "Больше не отвлекаю от компании. Что съешь — просто напиши, запишу без комментариев. 🥂"

def _esc(text) -> str:
    if text is None: return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_ALLOWED_TAGS = ("b", "i", "u", "s", "code", "pre", "em", "strong")

def _html_safe(text) -> str:
    """Экранируем всё, что вернул ИИ, но оставляем <b> и <i>.

    Telegram падает с ошибкой, если в HTML-сообщении встретится «&» или «<»
    без экранирования. ИИ такие символы выдаёт регулярно («белки & жиры»,
    «< 10 г»), и сообщение просто не отправлялось.
    """
    safe = _esc(text)
    pattern = r"&lt;(/?)(" + "|".join(_ALLOWED_TAGS) + r")&gt;"
    return re.sub(pattern, r"<\1\2>", safe)


async def _ai(func, *args, **kwargs):
    """Синхронный вызов ИИ — в отдельном потоке.

    Раньше запрос к модели выполнялся прямо в обработчике и на 5-20 секунд
    замораживал ВСЕХ пользователей бота: пока думает один, остальные ждут.
    """
    return await asyncio.to_thread(func, *args, **kwargs)


# блюда, у которых калорийность сильно зависит от состава — их считаем через вопрос
AMBIGUOUS_DISHES = {
    "котлета", "тефтеля", "плов", "шашлык", "гуляш", "шаурма", "салат", "паста",
    "пицца", "каша", "картофель", "пюре", "творог", "суп",
}

_LIQUID_NAMES = {
    "кола", "сок", "пиво", "вино", "крепкое", "вода", "кофе", "чай", "смузи", "кисель",
    "кефир", "молоко", "капучино", "латте", "раф", "американо", "эспрессо", "какао", "бабл ти",
}


SUGAR_DRINKS = (
    "чай", "кофе", "американо", "эспрессо", "капучино", "латте", "раф", "какао",
    "глинтвейн", "сок", "морс", "компот", "кисель", "лимонад", "коктейл", "смузи", "бабл",
    "кола", "пепси", "тоник", "энергетик", "фанта", "спрайт",
)

# напитки, у которых сахар по умолчанию есть — спрашиваем «обычная или Zero»
SWEET_BY_DEFAULT = ("кола", "пепси", "тоник", "энергетик", "фанта", "спрайт")
# основы слов: «кола», «колой», «колы» — одно и то же
SWEET_STEMS = ("кол", "пепси", "тоник", "фант", "спрайт", "энергетик")


def _has_stem(text: str, stems) -> bool:
    """Ищет слово с любым окончанием: «колой» -> основа «кол»."""
    low = (text or "").lower().replace("ё", "е")
    return any(re.search(rf"(?<![а-яё]){st}[а-яё]{{0,3}}(?![а-яё])", low) for st in stems)

# сок: важен не сахар в ложках, а свежевыжатый он или пакетированный
JUICE_WORDS = ("сок", "нектар")
# компот, морс, кисель: либо сладкий, либо без сахара
COMPOTE_WORDS = ("компот", "морс", "кисель")


# крепкое и вино: в смеси с колой это один напиток, а не составное блюдо
ALCOHOL_WORDS = ("виски", "водк", "ром", "джин", "коньяк", "текил", "ликер", "бренди",
                 "самогон", "абсент", "мартини", "шампанск", "вино", "пиво", "спирт")


def _needs_sugar_question(text: str) -> bool:
    """Напиток, про который не сказано про сахар — спрашиваем один раз."""
    low = (text or "").lower().replace("ё", "е")
    if not (any(d in low for d in SUGAR_DRINKS) or _has_stem(low, SWEET_STEMS)):
        return False
    return not any(w in low for w in ("сахар", "сладк", "несладк", "без добавок", "зеро", "zero", "диетическ"))


COFFEE_MILK_WORDS = ("латте", "капучино", "раф", "флэт", "мокка", "маккиато", "кофе с молоком")


_FAT_WORDS = {
    "обезжирен": 0, "без жира": 0, "нулев": 0, "ноль": 0,
    "полтора": 1.5, "полторы": 1.5,
    "три и два": 3.2, "три, два": 3.2, "три с половиной": 3.5,
    "два с половиной": 2.5, "две с половиной": 2.5,
    "один": 1, "одна": 1, "единиц": 1, "два": 2, "две": 2, "три": 3,
    "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9, "десять": 10, "пятнадцать": 15, "двадцать": 20,
}


def _parse_fat(text: str):
    """Жирность из свободного ответа: «15%», «один», «три и два», «20 г, 15%»."""
    low = (text or "").lower().replace("ё", "е").strip()

    # 1) процент — самый надёжный
    pct = re.search(r"(\d+(?:[.,]\d+)?)\s*%", low)
    if pct:
        v = float(pct.group(1).replace(",", "."))
        if 0 <= v <= 60:
            return v

    # 2) число без единиц — но не то, что с граммами/миллилитрами
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)(\s*(?:г|гр|грамм\w*|мл))?", low):
        if m.group(2):
            continue
        v = float(m.group(1).replace(",", "."))
        if 0 <= v <= 60:
            return v

    # 3) словами
    for word, value in sorted(_FAT_WORDS.items(), key=lambda kv: -len(kv[0])):
        if word in low:
            return value
    return None


def _drink_fields(text: str, kind: str):
    """Раздельные вопросы про напиток: объём, сахар, молоко — по одному."""
    low = (text or "").lower().replace("ё", "е")
    fields, qs = [], []
    if not _has_volume(text):
        fields.append("volume")
        qs.append("Сколько миллилитров? Например: 250 или 0,5 л.")
    if kind == "sweet":
        fields.append("sugar")
        qs.append("Обычная или Zero?")
    elif kind == "juice":
        fields.append("sugar")
        qs.append("Свежевыжатый или пакетированный?")
    elif kind == "compote":
        fields.append("sugar")
        qs.append("Сладкий или без сахара?")
    else:
        fields.append("sugar")
        qs.append("С сахаром или без? Если с сахаром — сколько ложек или граммов?")
        if any(w in low for w in COFFEE_MILK_WORDS):
            fields.append("milk")
            qs.append("Какое молоко — обычное, обезжиренное или безлактозное?")
    return fields[:3], qs[:3]


def _parse_drink_answer(field: str, answer: str, kind: str) -> str:
    a = (answer or "").lower().replace("ё", "е").strip()

    if field == "volume":
        if any(w in a for w in ("не знаю", "незнаю", "на глаз", "как обычно")):
            return "объём не указан — возьми стандартную порцию"
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(мл|л|литр\w*)", a)
        if m:
            n = float(m.group(1).replace(",", "."))
            if m.group(2).startswith(("л", "литр")):
                return f"{int(round(n * 1000))} мл"
            return f"{int(round(n))} мл"
        m = re.search(r"\b(\d{1,4})\b", a)
        if m:
            return f"{int(m.group(1))} мл"
        return ""

    if field == "sugar":
        if kind == "sweet":
            if any(w in a for w in ("zero", "зеро", "лайт", "диетическ", "без сахар", "нет")):
                return "без сахара (зеро)"
            return "обычная, с сахаром"
        if kind == "juice":
            if any(w in a for w in ("свеж", "фреш")):
                return "свежевыжатый, без добавленного сахара"
            if any(w in a for w in ("без сахар",)):
                return "пакетированный, без добавленного сахара"
            if any(w in a for w in ("пакет", "магазин", "коробк")):
                return "пакетированный, с сахаром"
            return ""
        if kind == "compote":
            if any(w in a for w in ("сладк", "с сахаром")):
                return "сладкий, с сахаром"
            if any(w in a for w in ("без сахар", "нет")):
                return "без сахара"
        if any(w in a for w in ("без сахар", "нет", "неа", "ничего", "просто")):
            return "без сахара"
        spoons = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:ложк|ч\.?\s*л)", a)
        if spoons:
            return f"сахар {spoons.group(1).replace(',', '.')} ч.л."
        grams = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:г|гр|грамм)", a)
        if grams:
            return f"сахар {grams.group(1).replace(',', '.')} г"
        bare = re.search(r"\b([1-9])\b", a)
        if bare:
            return f"сахар {bare.group(1)} ч.л."
        return "без сахара"

    if field == "milk":
        if any(w in a for w in ("безлактоз", "овсян", "миндальн", "соев", "растительн", "кокосов")):
            return "растительное или безлактозное молоко"
        if "обезжир" in a:
            return "обезжиренное молоко"
        if any(w in a for w in ("обычн", "2,5")):
            return "обычное молоко 2,5%"
        return ""

    return answer


def _has_volume(text: str) -> bool:
    """Назван ли объём/вес: «300», «0,5 л», «стакан», «две чашки»."""
    low = (text or "").lower().replace("ё", "е")
    if re.search(r"\d", low):
        return True
    return any(w in low for w in ("стакан", "чашк", "кружк", "бокал", "рюмк", "стопк", "бутылк", "полтора", "пол литра", "пол-литра"))


def _sugar_kind(text: str) -> str:
    """Какой вопрос уместен: сок / компот / обычная-или-Zero / ложки."""
    low = (text or "").lower().replace("ё", "е")
    if any(w in low for w in JUICE_WORDS):
        return "juice"
    if any(w in low for w in COMPOTE_WORDS):
        return "compote"
    if _has_stem(low, SWEET_STEMS):
        return "sweet"
    return "spoon"


_DRINK_WORDS = ("кофе", "капучино", "латте", "американо", "эспрессо", "флэт", "раф",
                "чай", "сок", "кола", "лимонад", "вода", "вино", "пиво", "компот",
                "коктейль", "какао", "смузи", "бабл", "морс", "квас", "милкшейк")

def _is_drink_name(name: str) -> bool:
    low = (name or "").lower()
    return any(w in low for w in _DRINK_WORDS)

def _fix_menu_variant(v):
    """В варианте не больше одного напитка и без повторов позиций."""
    if not isinstance(v, dict):
        return v
    items = [dict(i) for i in (v.get("items") or []) if isinstance(i, dict)]
    if not items:
        return v
    seen_names, kept, seen_drink = set(), [], False
    for it in items:
        nm = _normalize(it.get("name") or "")
        if not nm or nm in seen_names:
            continue
        if _is_drink_name(nm):
            if seen_drink:
                continue
            seen_drink = True
        seen_names.add(nm)
        kept.append(it)
    if len(kept) == len(items):
        return v
    out = dict(v)
    out["items"] = kept
    out["dish"] = " + ".join(str(i.get("name") or "") for i in kept)
    out["calories"] = sum(int(float(i.get("calories") or 0)) for i in kept)
    return out

def _zone_choice(raw: str):
    """Какой из трёх вариантов выбрал человек: номер, цвет или слово."""
    t = (raw or "").lower().replace("ё", "е").strip()
    if t in ("1", "первый", "первое", "первая"):
        return "green"
    if t in ("2", "второй", "второе", "вторая"):
        return "yellow"
    if t in ("3", "третий", "третье", "третья"):
        return "red"
    if any(w in t for w in ("зелен", "🌱", "похуден", "худеть")):
        return "green"
    if any(w in t for w in ("желт", "🌿", "поддерж")):
        return "yellow"
    if any(w in t for w in ("красн", "🍃", "праздник", "поплотнее")):
        return "red"
    return None


def _zone_text(zone: dict) -> str:
    """«Капучино (140 ккал) + Круасан (320 ккал)» — калории по каждой позиции."""
    parts = []
    for item in (zone.get("items") or [])[:2]:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        parts.append(f"<b>{_esc(name)}</b> ({int(item.get('calories') or 0)} ккал)")
    if parts:
        return " + ".join(parts)
    return f"<b>{_esc(zone.get('dish'))}</b> ({int(zone.get('calories') or 0)} ккал)"


def _quick_details(text: str):
    """Если количество уже названо — считаем сразу, без вопросов (BUG-16/17/22)."""
    # вино без типа (сухое/сладкое) сразу не считаем
    if ai.needs_wine_question(text, []):
        return None
    # рецептные блюда («по-французски») считаем через ИИ, а не как ингредиент
    if ai.needs_recipe_question(text, []):
        return None
    # мясо и рыба: без способа приготовления «сразу» не считаем
    if ai.needs_cooking_question(text, []):
        return None
    # молочные: без жирности «сразу» не считаем
    if ai.needs_fat_question(text, []):
        return None
    low = text.lower().replace("ё", "е").strip()
    modifiers = []
    for phrase in ("без сахара", "с сахаром", "без молока", "с молоком", "несладкий",
                   "сладкий", "без сиропа", "с сиропом", "без меда", "с медом"):
        if phrase in low:
            modifiers.append(phrase)
            low = low.replace(phrase, " ")
    low = " ".join(low.split())
    suffix = (", " + ", ".join(modifiers)) if modifiers else ""

    match = re.match(
        r"^(?P<name>[а-яa-z0-9\s\-]+?)\s*(?P<num>\d+(?:[.,]\d+)?)\s*"
        r"(?P<unit>г|гр|грамм\w*|мл|л|литр\w*|шт|штук\w*)?$",
        low,
    )
    if not match:
        return None

    name = match.group("name").strip()
    amount = float(match.group("num").replace(",", "."))
    unit = (match.group("unit") or "").lower()

    key = None
    for candidate in sorted(list(ai.STANDARDS) + list(ai.SIZE_MIDDLE), key=len, reverse=True):
        if candidate.replace("ё", "е") in name:
            key = candidate
            break
    if not key or key in AMBIGUOUS_DISHES:
        return None

    if unit.startswith(("шт", "штук")):
        per = ai.SIZE_MIDDLE.get(key) or ai.STANDARDS.get(key) or 100
        return f"{int(round(amount * per))} г ({amount:g} шт по {per} г)" + suffix

    if unit.startswith(("л", "литр")):
        return f"{int(round(amount * 1000))} мл" + suffix
    if unit.startswith("мл"):
        return f"{int(round(amount))} мл" + suffix
    if unit.startswith(("г", "гр", "грамм")):
        return f"{int(round(amount))} г" + suffix

    # единицы нет: для напитков это мл, для штучных — штуки, иначе граммы
    if key in _LIQUID_NAMES:
        raw_num = match.group("num")
        # «2,5» без единицы — это жирность, а не объём; «0,5» — пол-литра
        if "%" in low:
            return None
        if amount < 1:
            return f"{int(round(amount * 1000))} мл" + suffix
        if amount <= 20:
            return None
        return f"{int(round(amount))} мл" + suffix
    if amount <= 10:
        # «яйцо 2», «сырники 3» — это штуки, а не граммы
        per = ai.SIZE_MIDDLE.get(key) or ai.STANDARDS.get(key)
        if per:
            return f"{int(round(amount * per))} г ({amount:g} шт по {per} г)" + suffix
        return None
    return f"{int(round(amount))} г" + suffix


def _merge_component(acc: dict, fd: dict, fallback_name: str = "") -> dict:
    """Складываем компоненты блюда, не теряя «жидкость», объём, сахар и вредные жиры.

    Раньше суммировались только калории/БЖУ/вес/соль, поэтому «виски + кола»
    записывалось как твёрдая еда с нулевым сахаром и без объёма.
    """
    for field in ("calories", "protein", "fat", "carbs", "weight", "salt", "sugar", "bad_fat"):
        acc[field] = acc.get(field, 0) + (fd.get(field, 0) or 0)
    if fd.get("is_liquid"):
        acc["is_liquid"] = True
        acc["ml"] = (acc.get("ml") or 0) + (fd.get("ml") or fd.get("weight") or 0)
    if not isinstance(acc.get("dish"), list):
        acc["dish"] = [acc["dish"]] if acc.get("dish") else []
    acc["dish"].append(fd.get("dish") or fallback_name)
    return acc


def _get_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]

def _main_menu_keyboard(user: dict) -> ReplyKeyboardMarkup:
    utc_offset = user.get('utc_offset') or 3
    user_now = datetime.utcnow() + timedelta(hours=utc_offset)

    buttons = [[KeyboardButton(text=BTN_EAT)]]
    buttons.append([KeyboardButton(text=BTN_KOTIK)])
    buttons.append([KeyboardButton(text=BTN_MENU)])

    if user_now.hour >= 19:
        buttons.append([KeyboardButton(text=BTN_SUMMARY)])

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True, is_persistent=True,
    )

def _kotik_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_HELP)],
            [KeyboardButton(text=BTN_EVENING)],
            [KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True, is_persistent=True,
    )


def _menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_MENU_SEARCH)],
            [KeyboardButton(text=BTN_EAT_OUT)],
            [KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True, is_persistent=True,
    )


def _continue_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CONTINUE)]], resize_keyboard=True, is_persistent=True)

def _agree_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_AGREE)]], resize_keyboard=True, is_persistent=True)

def _timezone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="UTC+2 (Калининград)")], [KeyboardButton(text="UTC+3 (Москва, Питер)")],
            [KeyboardButton(text="UTC+4 (Самара, Ижевск)")], [KeyboardButton(text="UTC+5 (Екатеринбург, Ташкент)")],
            [KeyboardButton(text="UTC+6 (Омск, Астана)")], [KeyboardButton(text="UTC+7 (Новосибирск, Красноярск)")],
        ],
        resize_keyboard=True, is_persistent=True,
    )

def _food_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Исправить", callback_data="fix_last")],
        [InlineKeyboardButton(text="🗑 Убрать из дневника", callback_data="delete_last")]
    ])

def _menu_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐾 Поищем по меню", callback_data="menu_build")],
        [InlineKeyboardButton(text="🍽 Иду в ресторан", callback_data="menu_restaurant")]
    ])

def _help_yes_no_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_HELP_YES, callback_data="help_yes"),
         InlineKeyboardButton(text=BTN_HELP_NO, callback_data="help_no")]
    ])

def _calc_norms(user: dict) -> dict:
    weight = float(user['weight']) if user and user.get('weight') else 70.0
    height = user.get('height') if user and user.get('height') else 170
    age = user.get('age') if user and user.get('age') else 30
    gender = user.get('gender') if user and user.get('gender') else 'Ж'
    lifestyle = (user.get('lifestyle') or 'умеренный').lower()

    if gender == "М": bmr = (10 * weight) + (6.25 * height) - (5 * age) + 5
    else: bmr = (10 * weight) + (6.25 * height) - (5 * age) - 161

    if "сидяч" in lifestyle: mult = 1.2
    elif "актив" in lifestyle: mult = 1.55
    else: mult = 1.375

    support_center = int(bmr * mult)
    support_low = int(round((support_center - 100) / 50.0) * 50)
    support_high = int(round((support_center + 100) / 50.0) * 50)
    loss_center = max(support_center - 400, 1500 if gender == "М" else 1200)
    loss_low = int(round((loss_center - 100) / 50.0) * 50)
    loss_high = int(round((loss_center + 100) / 50.0) * 50)

    ideal_weight = height - (100 if gender == "М" else 110)
    corrected_weight = ideal_weight + (weight - ideal_weight) * 0.25
    prot_center = corrected_weight * 1.2
    prot_low, prot_high = int(prot_center * 0.9), int(prot_center * 1.1)

    norms = {"support_low": support_low, "support_high": support_high, "loss_low": loss_low, "loss_high": loss_high,
             "protein_low": prot_low, "protein_high": prot_high, "weight": weight, "corrected_weight": corrected_weight}
    water_low, water_high = database.get_water_range(user, norms)
    norms['water_low'], norms['water_high'] = water_low, water_high
    return norms

def _calc_percent(current, target):
    if not target or target == 0:
        return 0
    return min(100, int(round((current / target) * 100)))

def _calc_percent_range(current, low, high):
    """Процент от диапазона: сначала к верхней границе, потом к нижней (23–24 %)."""
    return f"{_calc_percent(current, max(low, high))}–{_calc_percent(current, min(low, high))}"

def _normalize(text: str) -> str:
    """Нормализация для сверки блюд: без кавычек, регистра, ё/е, лишних пробелов."""
    if not text:
        return ""
    t = str(text).lower().strip()
    t = t.replace("ё", "е")
    t = re.sub(r"[«»\"'`„“”]", "", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[,;.!?]+$", "", t).strip()
    return t

async def _send_day_summary(message: types.Message, user_id: int):
    user = database.get_user(user_id)
    today_str = database._get_user_date(user_id, (user.get('utc_offset') or 3))
    summary = database.get_day_summary(user_id, today_str)
    liquid_total = database.get_day_liquid(user_id, today_str)

    if summary is None and liquid_total == 0:
        await message.answer("Сегодня ты еще ничего не записывал. Присылай, что съел!")
        return

    norms = _calc_norms(user)
    day_cal = int(summary['calories']) if summary else 0
    day_prot = summary['protein'] if summary else 0
    day_fat = summary['fat'] if summary else 0
    day_carb = summary['carbs'] if summary else 0
    target_cal = norms['loss_high']

    if day_cal > (target_cal + 500):
        if _no_guilt_shown_today.get(user_id) != today_str:
            conn = database._connect()
            cursor = conn.cursor()
            cursor.execute('SELECT dish FROM food_log WHERE user_id = ? AND date = ?', (user_id, today_str))
            rows = cursor.fetchall()
            conn.close()
            dishes = [r['dish'] for r in rows if r['dish']]

            no_guilt_text = await _ai(ai.generate_no_guilt_message, day_cal, target_cal, dishes)
            await message.answer(_html_safe(no_guilt_text))
            _no_guilt_shown_today[user_id] = today_str
            return
        else:
            await message.answer("Мы рядом. Всё хорошо. 💚")
            return

    partial = bool(target_cal) and day_cal < target_cal * 0.35

    if user.get('week', 1) == 1:
        ai_text = await _ai(ai.generate_day_summary, user, summary, liquid_total, partial) or "Записал, что было. Продолжаем 💚"
        await message.answer(
            f"🔥 <b>За сегодня:</b> {day_cal} ккал | Б {day_prot} / Ж {day_fat} / У {day_carb}\n"
            f"💧 Жидкость: {liquid_total} мл\n\n"
            f"{_html_safe(ai_text)}",
            reply_markup=_main_menu_keyboard(user)
        )
    else:
        p_cal = _calc_percent_range(day_cal, norms['loss_low'], norms['loss_high'])
        p_prot = _calc_percent(day_prot, norms['protein_high'])
        p_water = _calc_percent(liquid_total, norms['water_high'])

        ai_text = await _ai(ai.generate_day_summary, user, summary, liquid_total, partial) or "Хороший ритм! 💚"

        text = (
            f"🐾 <b>Твои итоги дня:</b>\n"
            f"🔥 Калории: {day_cal} из {norms['loss_low']}–{norms['loss_high']} ккал (<b>{p_cal}%</b>)\n"
            f"🥩 Белок: {day_prot} из {norms['protein_high']} г ({p_prot}%)\n"
            f"💧 Жидкость: {liquid_total} из {norms['water_high']} мл ({p_water}%)\n\n"
            f"{_html_safe(ai_text)}"
        )
        await message.answer(text, reply_markup=_main_menu_keyboard(user))

# ==================== ОБРАБОТЧИКИ КНОПОК МЕНЮ (INLINE) ====================

@dp.callback_query(F.data == "menu_build")
async def cb_menu_build(callback: CallbackQuery):
    user_id = callback.from_user.id
    _pending_menu_mode[user_id] = {"waiting": True}
    await callback.message.edit_text("Пришли меню (фото или текстом), и я подскажу, что выбрать. Соберу для тебя вкусный и удобный вариант, глядя на твои цифры. Без запретов, просто чтобы ты видел картину. 💚")
    await callback.answer()

@dp.callback_query(F.data == "menu_restaurant")
async def cb_menu_restaurant(callback: CallbackQuery):
    await callback.message.edit_text("Ой, эту кнопку мы ещё пилим! 🐾 Бот пока не умеет искать меню по названию заведения. Но мы работаем над этим с утра до ночи и скоро настроим. А пока — просто нажми «Собери меню» или пришли фото меню, и я помогу сориентироваться!")
    await callback.answer()

# ==================== ОБРАБОТЧИКИ КНОПОК ДА/НЕТ В ПОМОЩИ ====================

@dp.callback_query(F.data == "help_yes")
async def cb_help_yes(callback: CallbackQuery):
    user_id = callback.from_user.id
    _help_waiting_answer.discard(user_id)
    await callback.message.edit_text("🐾 Ушки на макушке, слушаю 💚")
    await callback.answer()

@dp.callback_query(F.data == "help_no")
async def cb_help_no(callback: CallbackQuery):
    user_id = callback.from_user.id
    _help_waiting_answer.discard(user_id)
    _help_mode.discard(user_id)
    user = database.get_user(user_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("Не удалось убрать кнопки", exc_info=True)
    await callback.message.answer("😺 Хорошо, возвращаемся к записи еды. Присылай, что съел — текстом или фото.",
                                  reply_markup=_main_menu_keyboard(user))
    await callback.answer()

# ==================== СТАРЫЕ ОБРАБОТЧИКИ ====================

def _day_summary_lines(user_id: int, today_str: str, user: dict) -> str:
    """Сводка за день в том же виде, что и после записи еды."""
    norms = _calc_norms(user)
    summary = database.get_day_summary(user_id, today_str)
    liquid_total = database.get_day_liquid(user_id, today_str)

    day_cal = int(summary['calories']) if summary else 0
    day_prot = summary['protein'] if summary else 0
    day_fat = summary['fat'] if summary else 0
    day_carb = summary['carbs'] if summary else 0

    if day_cal == 0:
        return "📊 <b>За сегодня:</b> пока пусто"

    if user.get('week', 1) == 1:
        return (f"📊 <b>За сегодня:</b> {day_cal} ккал | Б {day_prot} / Ж {day_fat} / У {day_carb}\n"
                f"💧 Жидкость: {liquid_total} мл")

    target_cal = norms['loss_high']
    target_prot = norms['protein_high']
    target_water = norms['water_high']
    return (f"📊 <b>За сегодня:</b> {day_cal} из {norms['loss_low']}–{norms['loss_high']} ккал ({_calc_percent_range(day_cal, norms['loss_low'], norms['loss_high'])}%)\n"
            f"🥩 Белок: {day_prot} из {target_prot} г ({_calc_percent(day_prot, target_prot)}%)\n"
            f"💧 Жидкость: {liquid_total} из {target_water} мл ({_calc_percent(liquid_total, target_water)}%)")


@dp.callback_query(F.data == "delete_last")
async def cb_delete_last(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = database.get_user(user_id)
    today_str = database._get_user_date(user_id, (user.get('utc_offset') or 3))

    removed = database.delete_last_food(user_id, today_str)
    if not removed:
        await callback.message.answer("Не нашёл последнюю запись за сегодня.")
        await callback.answer()
        return

    text = f"🗑 Запись удалена: <b>{_esc(removed)}</b>"
    try:
        await callback.message.edit_text(text, reply_markup=None)
    except Exception:
        logger.debug("Не удалось отредактировать сообщение об удалении", exc_info=True)
        await callback.message.answer(text)
    await callback.answer()

async def cb_sugar(callback: CallbackQuery):
    user_id = callback.from_user.id
    pending = _pending_clarification.get(user_id)
    if not pending or not pending.get("sugar"):
        await callback.answer("Это уже неактуально")
        return

    values = {
        "sugar_0": "без сахара",
        "sugar_1": "1 ложка сахара",
        "sugar_2": "2 ложки сахара",
        "sugar_yes": "обычная, с сахаром",
        "sugar_zero": "без сахара (зеро)",
        "sugar_fresh": "свежевыжатый, без добавленного сахара",
        "sugar_pack": "пакетированный, с сахаром",
        "sugar_sweet": "сладкий, с сахаром",
    }
    value = values.get(callback.data)
    if not value:
        await callback.answer("Это уже неактуально")
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("Не удалось убрать кнопки сахара", exc_info=True)

    user = database.get_user(user_id) or {}
    today_str = database._get_user_date(user_id, (user.get("utc_offset") or 3))
    await _handle_clarification_answer(callback.message, user_id, value, today_str)
    await callback.answer()


@dp.callback_query(F.data.in_({"sugar_0", "sugar_1", "sugar_2", "sugar_yes", "sugar_zero",
                               "sugar_fresh", "sugar_pack", "sugar_sweet"}))
async def cb_sugar_router(callback: CallbackQuery):
    await cb_sugar(callback)


@dp.callback_query(F.data == "fix_last")
async def cb_fix_last(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = database.get_user(user_id)
    today_str = database._get_user_date(user_id, (user.get('utc_offset') or 3))

    removed = database.delete_last_food(user_id, today_str)
    _active_menu.pop(user_id, None)
    _pending_menu_mode.pop(user_id, None)
    _pending_water.discard(user_id)
    # состояние не нужно: старая запись удалена, следующее сообщение — новая запись
    _pending_clarification.pop(user_id, None)

    if removed:
        try:
            await callback.message.edit_text(
                f"✏️ Запись убрана: <b>{_esc(removed)}</b>", reply_markup=None)
        except Exception:
            logger.debug("Не удалось отредактировать сообщение при исправлении", exc_info=True)
        await callback.message.answer(
            "Напиши заново, что записать? Например: «борщ 250».",
            reply_markup=_main_menu_keyboard(user) if user else None,
        )
    else:
        await callback.message.answer("Не нашёл запись за сегодня. Напиши, что записать?")
    await callback.answer()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user = database.get_user(user_id)
    if user is None:
        await message.answer("Привет! Мы ещё в стадии теста, поэтому введи код-приглашение — без него пользоваться ботом не получится. 🐾")
        return
    step = user['survey_step']
    if step == 99:
        await message.answer("🐾 Мы уже говорили про возраст. Когда тебе исполнится 18, будем рады познакомиться поближе!")
    elif step == 0:
        database.set_step(user_id, 1)
        await message.answer("Давай познакомимся. Как тебя зовут?")
    elif step < 10:
        await message.answer("Мы не закончили знакомство. Продолжим? Напиши любое сообщение.")
    else:
        await message.answer("Привет! Присылай, что съел.", reply_markup=_main_menu_keyboard(user))

@dp.message(Command("reset_test"))
async def cmd_reset_test(message: types.Message):
    user_id = message.from_user.id
    if not database.get_user(user_id):
        await message.answer("Сначала /start.")
        return
    conn = database._connect()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM food_log WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM water_log WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM weight_log WHERE user_id = ?', (user_id,))
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('UPDATE users SET week = 1, created_at = ?, last_norms_update = ? WHERE user_id = ?', (now_str, now_str, user_id))
    conn.commit()
    conn.close()
    database.set_step(user_id, 10)
    _help_mode.discard(user_id)
    _help_waiting_answer.discard(user_id)
    _pending_clarification.pop(user_id, None)
    _pending_week_end.discard(user_id)
    _pending_weekly_weight.discard(user_id)
    _pending_agree.discard(user_id)
    _no_guilt_shown_today.pop(user_id, None)
    _active_menu.pop(user_id, None)
    _pending_menu_mode.pop(user_id, None)
    _pending_water.discard(user_id)
    _evening.pop(user_id, None)
    await message.answer("🧹 Тест сброшен. Всё удалено. Ты на первой неделе.", reply_markup=_main_menu_keyboard(database.get_user(user_id)))

@dp.message()
async def handle_message(message: types.Message):
    async with _get_lock(message.from_user.id):
        await _handle_message_locked(message)

async def _handle_message_locked(message: types.Message):
    user_id = message.from_user.id
    user = database.get_user(user_id)
    text = message.text.strip() if message.text else ""
    text_lower = text.lower()

    if user is None:
        if text == INVITE_CODE:
            database.create_user(user_id)
            database.set_step(user_id, 1)
            await message.answer("Код верный! Давай познакомимся. Как тебя зовут?")
        else:
            await message.answer("Код не подошёл. Попробуй ещё раз — без кода пользоваться ботом не получится. 🐾")
        return

    if user_id in _pending_agree:
        if text == BTN_AGREE:
            _pending_agree.discard(user_id)
            await message.answer("🐾 Давай сверим часы, чтобы я понимал твой день. Выбери свой часовой пояс:", reply_markup=_timezone_keyboard())
            database.set_step(user_id, 35)
        else:
            await message.answer("Нажми, пожалуйста, кнопку ниже — без этого дальше не получится. 🐾", reply_markup=_agree_keyboard())
        return

    if user['survey_step'] == 35:
        tz_map = {"UTC+2 (Калининград)": 2, "UTC+3 (Москва, Питер)": 3, "UTC+4 (Самара, Ижевск)": 4, "UTC+5 (Екатеринбург, Ташкент)": 5, "UTC+6 (Омск, Астана)": 6, "UTC+7 (Новосибирск, Красноярск)": 7}
        if text in tz_map:
            database.save_answer(user_id, "utc_offset", tz_map[text])
            database.set_step(user_id, 3)
            await message.answer(
                "Отлично, часы сверены! Теперь я знаю твой часовой пояс. ⏰\n\n"
                "🐾 У нас есть два пути:\n\n"
                "1️⃣ <b>Неделя привычек</b> (рекомендовано) — мягкий старт. Семь дней просто записываем еду и напитки.\n\n"
                "2️⃣ <b>Полная программа</b> — сразу настроим ориентиры для снижения веса.\n\n"
                "Напиши 1 или 2.", reply_markup=ReplyKeyboardRemove()
            )
        else:
            await message.answer("Пожалуйста, выбери пояс из кнопок ниже.", reply_markup=_timezone_keyboard())
        return

    if user_id in _pending_weekly_weight:
        weight = _parse_weight(text)
        if weight is None:
            await message.answer("Пожалуйста, напиши вес цифрами (например: 75 или 75.5).")
            return
        _pending_weekly_weight.discard(user_id)
        today_str = database._get_user_date(user_id, (user.get('utc_offset') or 3))
        database.add_weight(user_id, today_str, weight)
        database.save_answer(user_id, "week", user.get('week', 1) + 1)
        await message.answer(f"⚖️ Вес записан: {weight} кг. Нормы обновим раз в 3 недели. Продолжаем!", reply_markup=_main_menu_keyboard(database.get_user(user_id)))
        return

    step = user['survey_step']
    if step < 10:
        await _handle_survey(message, user, user_id, text, step)
        return
    if step == 99:
        await message.answer("🐾 Мы уже говорили про возраст.")
        return
    if user_id in _pending_week_end:
        if text == BTN_CONTINUE:
            _pending_week_end.discard(user_id)
            database.set_step(user_id, 4)
            database.save_answer(user_id, "week", 2)
            await message.answer("🐾 <b>Первая неделя позади!</b>\n\nОтлично, теперь давай настроим твои ориентиры. Задам несколько вопросов. 💚", reply_markup=ReplyKeyboardRemove())
            await message.answer("🐾 Для расчётов мне нужно знать твой пол. Напиши <b>М</b> или <b>Ж</b>.")
            return
        await message.answer("Жми «Продолжаем?».", reply_markup=_continue_keyboard())
        return

    if step == 10:
        await _handle_work(message, user_id, text)

async def _handle_survey(message, user, user_id, text, step):
    if step == 1:
        database.save_answer(user_id, "name", text)
        database.set_step(user_id, 2)
        await message.answer("Сколько тебе лет?")
    elif step == 2:
        if not text.isdigit():
            await message.answer("Цифрами, пожалуйста.")
            return
        age = int(text)
        if age < 18:
            if user.get('age_attempts', 0) >= 1:
                await message.answer("🐾 <b>Давай немного подождём!</b>\n\nGOODKAT AI доступен с 18 лет. Береги себя! 🐾💚")
                database.set_step(user_id, 99)
                return
            database.save_answer(user_id, "age_attempts", 1)
            await message.answer("Точно? Введи возраст еще раз.")
            return
        database.save_answer(user_id, "age", age)
        database.set_step(user_id, 3)
        _pending_agree.add(user_id)
        await message.answer(
            "💚 <b>Пара важных слов перед началом</b>\n\n"
            "Забота о себе — это здорово и важно в любом возрасте. Я очень хочу помочь тебе на этом пути.\n\n"
            "Но чтобы наше путешествие было безопасным: если у тебя есть хронические заболевания, особенности здоровья или ты ждешь малыша — пожалуйста, сначала посоветуйся с врачом.\n\n"
            "Я берегу твое здоровье, ведь оно важнее любых цифр. 🐾",
            reply_markup=_agree_keyboard()
        )
    elif step == 3:
        if text == "1":
            database.set_step(user_id, 10)
            database.save_answer(user_id, "week", 1)
            await message.answer(
                "🐾 <b>НЕДЕЛЯ ПРИВЫЧЕК</b>\n\n"
                "7 дней, чтобы лучше узнать себя. Ты будешь рассказывать мне о своём питании, а я помогу всё записать.\n\n"
                + DIARY_HELP_TEXT + "\n\n" + DIARY_HELP_TAIL,
                reply_markup=_main_menu_keyboard(database.get_user(user_id))
            )
        elif text == "2":
            database.set_step(user_id, 4)
            await message.answer(
                "🐾 <b>ПОЛНАЯ ПРОГРАММА</b>\n\n"
                "Отлично, идём настраиваться! Задам несколько коротких вопросов.\n\n"
                "———\n\n"
                "🐾 Для расчётов мне нужно знать твой пол. Напиши <b>М</b> или <b>Ж</b>."
            )
        else:
            await message.answer("Напиши <b>1</b> или <b>2</b>.")
    elif step == 4:
        if text.upper() not in ["М", "Ж"]:
            await message.answer("Пожалуйста, напиши <b>М</b> или <b>Ж</b>. 🙏")
            return
        database.save_answer(user_id, "gender", text.upper())
        database.set_step(user_id, 5)
        await message.answer("Спасибо! А какой у тебя рост в см? (например, 170)")
    elif step == 5:
        if not text.isdigit():
            await message.answer("Напиши, пожалуйста, рост цифрами — например, 170. 🙂")
            return
        database.save_answer(user_id, "height", int(text))
        database.set_step(user_id, 6)
        await message.answer("Записал. Теперь вес в кг — можно с дробной частью (например, 70.5).")
    elif step == 6:
        weight = _parse_weight(text)
        if weight is None:
            await message.answer("Напиши, пожалуйста, вес цифрами — например, 70 или 70.5. 🙂")
            return
        database.save_answer(user_id, "weight", weight)
        today_str = database._get_user_date(user_id, (user.get('utc_offset') or 3))
        database.add_weight(user_id, today_str, weight)
        database.set_step(user_id, 7)
        await message.answer(
            "🐾 Нам остался последний шаг, чтобы посчитать твои нормы.\n\n"
            "Как обычно проходит твой день?\n"
            "1️⃣ Больше сижу (работа за компьютером, машина)\n"
            "2️⃣ Двигаюсь умеренно (прогулки, домашние дела)\n"
            "3️⃣ Много двигаюсь (активная работа, спорт)\n\n"
            "Напиши 1, 2 или 3. 💚"
        )
    elif step == 7:
        mapping = {"1": "сидячий", "2": "умеренный", "3": "активный"}
        if text not in mapping:
            await message.answer("Напиши, пожалуйста, <b>1</b>, <b>2</b> или <b>3</b>. 🙂")
            return
        database.save_answer(user_id, "lifestyle", mapping[text])
        database.set_step(user_id, 9)
        database.save_answer(user_id, "week", 2)
        await _show_norms_and_finish(message, user_id)

async def _show_norms_and_finish(message: types.Message, user_id: int):
    user = database.get_user(user_id)
    norms = _calc_norms(user)
    database.set_step(user_id, 10)
    database.save_answer(user_id, "last_norms_update", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    text_result = (
        "🐾 <b>Теперь у нас есть важные ориентиры!</b>\n\n"
        f"🔥 <b>Чтобы вес оставался примерно таким же</b> — около <b>{norms['support_low']}–{norms['support_high']}</b> ккал в день.\n\n"
        f"🎯 <b>Если хочется немного снизить вес</b> — попробуем диапазон <b>{norms['loss_low']}–{norms['loss_high']}</b> ккал в день.\n\n"
        f"🥚 <b>Белок</b> — примерно <b>{norms['protein_low']}–{norms['protein_high']}</b> г в день.\n\n"
        f"💧 <b>Жидкость</b> — около <b>{norms['water_low']}–{norms['water_high']}</b> мл.\n\n"
        "🧂 <b>Соль</b> — ориентир около <b>5 г</b> в день.\n\n"
        "Будем разбираться во всём постепенно, шаг за шагом. 💚"
    )
    await message.answer(text_result)

    await asyncio.sleep(1)
    await message.answer(DIARY_HELP_TEXT + "\n\n" + DIARY_HELP_TAIL, reply_markup=_main_menu_keyboard(user))

THANKS_WORDS = ("спасибо", "благодарю", "спс", "thanks")
GREET_WORDS = ("привет", "здравствуй", "хай", "добрый день", "добрый вечер", "доброе утро")
BYE_WORDS = ("пока", "до свидания", "до встречи", "бай")
OK_WORDS = ("ок", "окей", "хорошо", "понял", "поняла", "ясно", "ага", "угу")

def _word_hit(text: str, words) -> bool:
    """Совпадение по целым словам: «рибай» — это не «бай»."""
    for w in words:
        if re.search(r"(?<![а-яa-z])" + re.escape(w) + r"(?![а-яa-z])", text):
            return True
    return False


def _service_reply(text_lower: str):
    if _word_hit(text_lower, THANKS_WORDS): return "Пожалуйста! Если что — я рядом. 💚"
    if _word_hit(text_lower, GREET_WORDS): return "Привет! Присылай, что съел."
    if _word_hit(text_lower, BYE_WORDS): return "До связи! Не забудь записать. 👋"
    if text_lower in OK_WORDS: return "Хорошо! Жду, что съел."
    return None

async def _handle_work(message, user_id, text):
    text_lower = text.lower().strip()
    user = database.get_user(user_id)
    today_str = database._get_user_date(user_id, (user.get('utc_offset') or 3))

    # Проверка на режим "Собери меню"
    if user_id in _pending_menu_mode:
        if text in _CONTROL_BUTTONS:
            _pending_menu_mode.pop(user_id, None)
        else:
            if message.photo:
                await message.answer("Вижу фото меню. Исследую, разбираю на молекулы... 🐾")
                photo = message.photo[-1]
                file = await bot.get_file(photo.file_id)
                os.makedirs("downloads", exist_ok=True)
                file_path = f"downloads/{photo.file_id}.jpg"
                try:
                    await bot.download_file(file.file_path, file_path)
                    photo_result = await _ai(ai.analyze_menu_photo, file_path)
                finally:
                    if os.path.exists(file_path):
                        try: os.remove(file_path)
                        except OSError: pass
                if photo_result and photo_result.get("error"):
                    await message.answer("Не получилось посмотреть фото — сбой на моей стороне. Пришли ещё раз или напиши меню текстом. 🐾")
                    return
                menu_desc = photo_result.get("description", "") if photo_result else ""
                if not menu_desc:
                    await message.answer("🐾 Прости, не разобрал фото, пришли ещё раз или напиши что съел — я запишу 💚")
                    return
                text = menu_desc
            else:
                await message.answer("Смотрю меню, ищу, что подойдёт под твои цифры... 🐾")

            summary = database.get_day_summary(user_id, today_str)
            day_cal = int(summary['calories']) if summary else 0
            norms = _calc_norms(user)
            # Остаток от нормы похудения (верхняя граница)
            remaining_loss = max(0, norms['loss_high'] - day_cal)
            # Остаток от нормы поддержания (верхняя граница)
            remaining_support = max(0, norms['support_high'] - day_cal)

            is_first_week = user.get('week', 1) == 1

            if is_first_week:
                menu_res = await _ai(ai.analyze_menu_first_week, text)
            else:
                menu_res = await _ai(ai.analyze_menu_and_build_traffic_light, 
                    text, remaining_loss, remaining_support, day_cal,
                    norms['loss_high'], norms['support_high']
                )

            if not menu_res or not menu_res.get("is_menu"):
                await message.answer("🐾 Прости, не разобрал фото, пришли ещё раз или напиши что съел — я запишу 💚")
                return

            _pending_menu_mode.pop(user_id, None)

            if is_first_week:
                lighter = menu_res.get("lighter") or []
                denser = menu_res.get("denser") or []
                all_dishes = list(lighter) + list(denser)
                _active_menu[user_id] = {"week": 1, "lighter": lighter, "denser": denser, "all_dishes": all_dishes}
                reply_text = "🐾 Вот что получилось. Тут без цифр — просто покажу, что полегче, а что поплотнее 💚\n\n"
                if lighter:
                    reply_text += "🌱 <b>Полегче:</b>\n" + ", ".join(_esc(x) for x in lighter) + "\n\n"
                if denser:
                    reply_text += "🍃 <b>Поплотнее:</b>\n" + ", ".join(_esc(x) for x in denser) + "\n\n"
                reply_text += "🐾 Если что-то присмотрел — напиши, я запишу. Или напиши \"нет\", если передумал"
                await message.answer(reply_text)
            else:
                green = _fix_menu_variant(menu_res.get("green"))
                yellow = _fix_menu_variant(menu_res.get("yellow"))
                red = _fix_menu_variant(menu_res.get("red"))
                if red and (
                    not red.get("dish")
                    or int(red.get("calories") or 0) > 2500
                    or str(red.get("dish")).count(" + ") > 1
                ):
                    red = None
                all_dishes, all_items = [], []
                for d in (green, yellow, red):
                    if d and d.get("dish"):
                        all_dishes.append(d["dish"])
                        for it in (d.get("items") or []):
                            nm = str(it.get("name") or "").strip()
                            if nm:
                                all_items.append({"name": nm, "dish": d})
                _active_menu[user_id] = {"week": 2, "green": green, "yellow": yellow, "red": red,
                                         "all_dishes": all_dishes, "all_items": all_items}

                reply_text = "🐾 Вот что могу предложить:\n\n"
                if green and green.get("dish"):
                    reply_text += f"🐾 {_zone_text(green)}. Спокойно выбираем и всё равно продолжим худеть 💚\n\n"
                if yellow and yellow.get("dish"):
                    reply_text += f"🐾 {_zone_text(yellow)}. Чуть плотнее, но лишнего не наберём 🐾\n\n"
                if red and red.get("dish"):
                    reply_text += f"🐾 {_zone_text(red)}. Если очень хочется праздника. А завтра продолжим как обычно\n\n"
                if not any(bool(d and d.get("dish")) for d in (green, yellow, red)):
                    reply_text += "В этом меню не нашлось ничего подходящего. Напиши блюдо словами — посчитаю сам.\n\n"
                reply_text += ("Напиши, что выбрал: название блюда, номер варианта («1», «2», «3») "
                               "или «нет», если передумал.")
                await message.answer(reply_text)
            return

    # Обработка активного меню
    if user_id in _active_menu:
        menu_data = _active_menu[user_id]
        if text in _CONTROL_BUTTONS:
            _active_menu.pop(user_id, None)
        elif text_lower in ("нет", "неа", "хватит", "всё"):
            _active_menu.pop(user_id, None)
            _pending_menu_mode.pop(user_id, None)
            await message.answer("🐾 Хорошо, тогда просто вернёмся к записи еды. Что ты сегодня ел?", reply_markup=_main_menu_keyboard(user))
            return
        elif menu_data.get("week") == 2 and _zone_choice(text_lower):
            color_key = _zone_choice(text_lower)
            dish = menu_data.get(color_key)
            if not dish or not dish.get("dish"):
                await message.answer("В этой зоне сегодня пусто. Выбери другое блюдо или напиши свой вариант.")
                return
            _active_menu.pop(user_id, None)
            food_data = {
                "dish": dish.get("dish"),
                "weight": dish.get("weight", 100),
                "calories": dish.get("calories", 0),
                "protein": dish.get("protein", 0),
                "fat": dish.get("fat", 0),
                "carbs": dish.get("carbs", 0),
                "sugar": 0, "bad_fat": 0, "salt": 0, "is_liquid": False, "ml": None
            }
            await _save_food_and_reply(message, user_id, food_data, fallback_dish=dish.get("dish"), today_str=today_str, is_fix=False)
            await message.answer("Приятного аппетита! 💚")
            return
        else:
            all_dishes = menu_data.get("all_dishes", [])
            all_items = menu_data.get("all_items", [])
            norm_text = _normalize(text)

            # сначала точное совпадение с одной позицией — «записал одно блюдо» значит одно
            single = None
            for it in all_items:
                if _normalize(it.get("name", "")) == norm_text:
                    single = it
                    break
            if not single and norm_text:
                # человек написал коротко («грудка») — понимаем, о какой позиции речь;
                # но «борщ и салат» не схлопываем в одно блюдо
                candidates = [it for it in all_items
                              if norm_text in _normalize(it.get("name", ""))]
                if candidates:
                    single = min(candidates, key=lambda it: len(it.get("name", "")))
            if single:
                _active_menu.pop(user_id, None)
                await message.answer("Секунду, считаю...")
                name = single["name"]
                food_data = await _ai(ai.calculate_nutrition, name, name)
                if food_data and food_data.get('calories') is not None:
                    await _save_food_and_reply(message, user_id, food_data, fallback_dish=name,
                                               today_str=today_str, is_fix=False)
                else:
                    await message.answer("Не смог посчитать. Попробуй написать вес (например 200 г).")
                return

            matched = None
            for d in all_dishes:
                nd = _normalize(d)
                if nd and (norm_text in nd or nd in norm_text):
                    matched = d
                    break
            if matched:
                _active_menu.pop(user_id, None)
                await message.answer("Секунду, считаю...")
                food_data = await _ai(ai.calculate_nutrition, matched, matched)
                if food_data and food_data.get('calories') is not None:
                    await _save_food_and_reply(message, user_id, food_data, fallback_dish=matched, today_str=today_str, is_fix=False)
                else:
                    await message.answer("Не смог посчитать. Попробуй написать вес (например 200 г).")
                return
            _active_menu.pop(user_id, None)
            _pending_clarification[user_id] = {
                "original_text": text,
                "dish": text,
                "questions": ["🐾 Такого блюда я в меню не нашёл. Записать его отдельно? да/нет"],
                "answers": [],
                "current_index": 0,
                "is_fix": False,
                "is_menu_confirm": True
            }
            await message.answer(f"🐾 Такого блюда я в меню не нашёл. Записать «{_esc(text)}» отдельно? да/нет")
            return

    if message.photo:
        await _handle_photo(message, user_id, text if text else None)
        return

    if text == BTN_KOTIK:
        await message.answer("🐾 Я рядом. Могу подсказать по питанию или пожелать хорошего отдыха:", reply_markup=_kotik_keyboard())
        return

    if text == BTN_BACK:
        _evening.pop(user_id, None)
        await message.answer("Возвращаемся. Что делаем дальше?", reply_markup=_main_menu_keyboard(user))
        return

    if text == BTN_MENU_SEARCH:
        _pending_menu_mode[user_id] = {"waiting": True}
        await message.answer(
            "🐾 Пришли меню (фото или текстом) — подскажу, что выбрать под твои цифры. "
            "Без запретов, просто чтобы ты видел картину. 💚"
        )
        return

    if text == BTN_EAT_OUT:
        await message.answer(
            "🐾 Пока не умею искать меню по названию заведения — эту кнопку мы ещё делаем. "
            "А если пришлёшь фото меню или напишешь блюда текстом, я помогу сориентироваться прямо сейчас."
        )
        return

    if text == BTN_EVENING:
        await message.answer("Секунду, устроюсь поудобнее... 🐾")
        day = database.get_day_summary(user_id, today_str) or {}
        ctx = {
            "name": (user or {}).get("name") or "",
            "calories": day.get("calories") or 0,
            "support_norm": round((_calc_norms(user or {}).get("support_low", 0) +
                                   _calc_norms(user or {}).get("support_high", 0)) / 2),
            "hour": (datetime.utcnow() + timedelta(hours=((user or {}).get('utc_offset') or 3))).hour,
            "drinks": "",
        }
        ai_res = await _ai(ai.evening_messages, ctx)
        if ai_res and ai_res.get("intro"):
            intro = (_esc(ai_res["intro"]) +
                     "\n\nДальше просто записывай, что съел и выпил — я рядом и без комментариев. 🥂")
            phrases = [_esc(t) for t in ai_res.get("touches", [])]
        else:
            intro = EVENING_INTRO
            phrases = list(EVENING_TOUCHES)
        _evening[user_id] = {"date": today_str, "touches": 1, "phrases": phrases}
        await message.answer(intro, reply_markup=_main_menu_keyboard(user))
        return

    if text_lower in ("хватит", "выход", "закончили") and user_id in _evening:
        _evening.pop(user_id, None)
        await message.answer("Понял, больше не отвлекаю. Хорошего вечера! 🥂")
        return

    if text == BTN_WATER:
        _pending_water.add(user_id)
        await message.answer("💧 Сколько миллилитров воды? Напиши цифру, например 250.")
        return

    if user_id in _pending_water:
        match = re.search(r"\d+", text)
        if not match:
            await message.answer("Напиши объём цифрой, например 250.")
            return
        _pending_water.discard(user_id)
        ml = int(match.group())
        database.add_water(user_id, today_str, ml)
        total = database.get_day_liquid(user_id, today_str)
        await message.answer(f"💧 Записал {ml} мл воды. Всего за день: {total} мл.")
        return

    water_match = re.match(r"^(?:выпил[аи]?\s+)?(?:вод[аы]|водичк[аи])\s+(\d+(?:[.,]\d+)?)\s*(\u043cл|л|литр\w*)?", text_lower)
    if water_match:
        amount = float(water_match.group(1).replace(",", "."))
        unit = (water_match.group(2) or "").lower()
        ml = int(amount * 1000) if unit.startswith("л") else int(amount)
        if 0 < ml <= 5000:
            database.add_water(user_id, today_str, ml)
            total = database.get_day_liquid(user_id, today_str)
            await message.answer(f"💧 Записал {ml} мл воды. Всего за день: {total} мл.")
            return

    if text == BTN_EAT:
        _help_mode.discard(user_id)
        _help_waiting_answer.discard(user_id)
        _pending_clarification.pop(user_id, None)
        _active_menu.pop(user_id, None)
        _pending_menu_mode.pop(user_id, None)
        await message.answer("Пришли, что съел — текстом или фото.")
        return
    if text == BTN_SUMMARY or text_lower in ["день", "итог", "итоги"]:
        _help_mode.discard(user_id)
        _help_waiting_answer.discard(user_id)
        _pending_clarification.pop(user_id, None)
        _active_menu.pop(user_id, None)
        _pending_menu_mode.pop(user_id, None)

        # итог — только вечером, после 19:00 по времени человека
        user_now = datetime.utcnow() + timedelta(hours=(user.get('utc_offset') or 3))
        if user_now.hour < 19:
            await message.answer(
                "Итоги с оценкой пройденного пути сможем подвести после 19 часов, "
                "будет отдельная кнопка, а пока продолжаем записывать что съели и выпили."
            )
            return

        await _send_day_summary(message, user_id)
        return
    if text == BTN_HELP:
        _help_mode.add(user_id)
        _active_menu.pop(user_id, None)
        _pending_menu_mode.pop(user_id, None)
        await message.answer("Я тут! Спрашивай, что тебя интересует про еду или питание. 💚")
        return
    if text == BTN_MENU:
        _help_mode.discard(user_id)
        _help_waiting_answer.discard(user_id)
        _pending_clarification.pop(user_id, None)
        _active_menu.pop(user_id, None)
        _pending_menu_mode.pop(user_id, None)
        await message.answer(
            "🐾 Хочется зайти красиво и не думать о цифрах?\n\n"
            "Я уже за столиком, меню в лапах: пришли его — разберу по калориям и предложу вариант на вечер. "
            "А если меню пока нет, сориентирую, как выбирать на месте.",
            reply_markup=_menu_keyboard(),
        )
        return

    if user_id in _help_waiting_answer:
        if text_lower in ("да", "ага", "угу", "конечно"):
            _help_waiting_answer.discard(user_id)
            await message.answer("🐾 Ушки на макушке, слушаю 💚")
            return
        elif text_lower in ("нет", "неа", "хватит", "всё"):
            _help_waiting_answer.discard(user_id)
            _help_mode.discard(user_id)
            await message.answer("😺 Хорошо, возвращаемся к записи еды. Что ты сегодня ел?", reply_markup=_main_menu_keyboard(user))
            return
        else:
            # человек вместо «да/нет» задал новый вопрос — отвечаем на него,
            # а не заставляем нажимать кнопки
            if user_id in _help_mode and ("?" in text):
                _help_waiting_answer.discard(user_id)
                await message.answer("Секунду, думаю...")
                answer = await _safe_ask_ai(text)
                if answer:
                    await message.answer(f"{_html_safe(answer)}\n\n🐾 Хочешь что-то ещё узнать? 💚", reply_markup=_help_yes_no_keyboard())
                    _help_waiting_answer.add(user_id)
                else:
                    await message.answer("Не смог ответить.")
                return
            await message.answer("Напиши 'да' или 'нет'.")
            return

    if user_id in _help_mode:
        if any(w in text_lower for w in THANKS_WORDS):
            _help_mode.discard(user_id)
            await message.answer("Пожалуйста! Если что — я рядом. 💚")
            return
        await message.answer("Секунду, думаю...")
        answer = await _safe_ask_ai(text)
        if answer:
            await message.answer(f"{_html_safe(answer)}\n\n🐾 Хочешь что-то ещё узнать? 💚", reply_markup=_help_yes_no_keyboard())
            _help_waiting_answer.add(user_id)
        else:
            await message.answer("Не смог ответить.")
        return

    if user_id in _pending_clarification:
        if _word_hit(text_lower, THANKS_WORDS + GREET_WORDS + BYE_WORDS):
            _pending_clarification.pop(user_id, None)
            service = _service_reply(text_lower)
            if service: await message.answer(service); return
        else:
            await _handle_clarification_answer(message, user_id, text, today_str)
            return

    service = _service_reply(text_lower)
    if service: await message.answer(service); return

    VAGUE = ("обычное", "обычный", "обычная", "стандарт", "да", "нет", "не знаю", "как обычно", "без сахара")
    if text_lower in VAGUE:
        await message.answer(
            "Не понял, к какому блюду это относится — похоже, я потерял предыдущий вопрос. "
            "Напиши, пожалуйста, что съел целиком, например: «капучино 200»."
        )
        return

    if not text:
        await message.answer("Я понимаю только текст и фото.")
        return

    await message.answer("Секунду, смотрю...")

    components = await _ai(ai.split_components, text)
    low_text = (text or "").lower().replace("ё", "е")
    mixed_drink = (_has_stem(low_text, SWEET_STEMS)
                   and any(w in low_text for w in ALCOHOL_WORDS))
    if mixed_drink:
        components = [text]  # «виски с колой» — один напиток: спрашиваем объём и Zero
    if len(components) > 1:
        total = {"calories": 0, "protein": 0, "fat": 0, "carbs": 0, "weight": 0, "dish": [], "is_liquid": False, "ml": None, "sugar": 0, "bad_fat": 0, "salt": 0}
        for comp in components:
            comp_res = await _ai(ai.get_questions_for_ai, comp)
            comp_dish = comp_res.get("dish", comp)
            # у составного блюда спрашиваем только порцию: иначе вопросов не счесть
            comp_q = ai.ensure_questions(comp, comp_res.get("questions", []))[:1]
            if comp_q:
                _pending_clarification[user_id] = {
                    "original_text": comp,
                    "dish": comp_dish,
                    "questions": comp_q,
                    "answers": [],
                    "current_index": 0,
                    "is_fix": False,
                    "is_component": True,
                    "remaining_components": components[components.index(comp)+1:],
                    "accumulated": total
                }
                await message.answer(f"Понял: {_esc(comp_dish)}. {_esc(comp_q[0])}")
                return
            else:
                fd = await _ai(ai.calculate_nutrition, comp_dish, comp)
                if fd and fd.get('calories') is not None:
                    _merge_component(total, fd, comp_dish)
        total["dish"] = " + ".join(total["dish"])
        await _save_food_and_reply(message, user_id, total, fallback_dish=total["dish"], today_str=today_str, is_fix=False)
        return

    if _needs_sugar_question(text):
        kind = _sugar_kind(text)
        fields, qs = _drink_fields(text, kind)
        _pending_clarification[user_id] = {
            "drink": True,
            "kind": kind,
            "dish": text,
            "original_text": text,
            "fields": fields,
            "questions": qs,
            "answers": [],
            "current_index": 0,
            "is_fix": False,
        }
        await message.answer(f"Понял: {_esc(text)}. {_esc(qs[0])}")
        return

    quick = _quick_details(text)
    if quick:
        food_data = await _ai(ai.calculate_nutrition, text, quick)
        if food_data and food_data.get('calories') is not None:
            await _save_food_and_reply(message, user_id, food_data, fallback_dish=text,
                                       today_str=today_str, is_fix=False)
            return

    ai_res = await _ai(ai.get_questions_for_ai, text)
    dish = ai_res.get("dish", text)
    questions = ai.ensure_questions(text, ai_res.get("questions", []))
    if questions and user_id in _evening:
        # «Тёплый вечер» — не допрашиваем: считаем по среднему и пишем «примерно»
        questions = []

    if not questions:
        food_data = await _ai(ai.calculate_nutrition, dish, text)
        if food_data and food_data.get('calories') is not None:
            await _save_food_and_reply(message, user_id, food_data, fallback_dish=dish, today_str=today_str, is_fix=False)
        else:
            await message.answer("Не смог посчитать. Попробуй написать вес (например 200 г).")
        return

    _pending_clarification[user_id] = {
        "original_text": text,
        "dish": dish,
        "questions": questions,
        "answers": [],
        "current_index": 0,
        "is_fix": False
    }

    await message.answer(f"Понял: {_esc(dish)}. {_esc(questions[0])}")

async def _handle_clarification_answer(message, user_id, text, today_str):
    pending = _pending_clarification.get(user_id)
    if not pending: return

    if pending.get("photo_confirm"):
        low = text.strip().lower().replace("ё", "е")
        desc = pending.get("original_text", "")
        if low in ("да", "ага", "угу", "верно", "все верно", "конечно", "точно", "так"):
            _pending_clarification.pop(user_id, None)
            ask_text = pending.get("ask_text") or desc
            if pending.get("is_compound"):
                # составное блюдо считаем по компонентам: одним запросом модель теряла часть тарелки
                await message.answer("Хорошо, уточню по частям.")
                await _handle_work(message, user_id, ask_text)
                return
            ai_res = await _ai(ai.get_questions_for_ai, ask_text)
            dish = ai_res.get("dish", ask_text) or ask_text
            questions = ai.ensure_questions(ask_text, ai_res.get("questions", []))
            if not questions:
                # название понятно и вес уже назван — считаем сразу
                await message.answer(f"Понял. Секунду, считаю «{_esc(dish)}»...")
                food_data = await _ai(ai.calculate_nutrition, dish, desc)
                if food_data and food_data.get("calories") is not None:
                    await _save_food_and_reply(message, user_id, food_data, fallback_dish=dish,
                                               today_str=today_str, is_fix=False)
                else:
                    await message.answer("Не смог посчитать. Напиши, пожалуйста, что это и сколько — например: борщ 300 г.")
                return
            _pending_clarification[user_id] = {
                "original_text": desc, "dish": dish, "questions": questions,
                "answers": [], "current_index": 0, "is_fix": False,
            }
            await message.answer(f"Понял: {_esc(dish)}. {_esc(questions[0])}")
            return
        if low in ("нет", "не", "неа", "неверно", "не верно", "неточно", "не это"):
            _pending_clarification.pop(user_id, None)
            await message.answer("Ой, извини, ещё учусь. Напиши, пожалуйста, что съел или выпил — например: борщ 300 г. 🐾")
            return
        # человек сразу написал правильное название — обрабатываем как обычный текст
        _pending_clarification.pop(user_id, None)
        await _handle_work(message, user_id, text)
        return

    if pending.get("is_menu_confirm"):
        _pending_clarification.pop(user_id, None)
        if text.lower() in ("да", "ага", "угу", "конечно"):
            await message.answer("Секунду, смотрю...")
            ai_res = await _ai(ai.get_questions_for_ai, pending["original_text"])
            dish = ai_res.get("dish", pending["original_text"])
            questions = ai.ensure_questions(pending["original_text"], ai_res.get("questions", []))

            if not questions:
                food_data = await _ai(ai.calculate_nutrition, dish, pending["original_text"])
                if food_data and food_data.get('calories') is not None:
                    await _save_food_and_reply(message, user_id, food_data, fallback_dish=dish, today_str=today_str, is_fix=False)
                else:
                    await message.answer("Не смог посчитать.")
            else:
                _pending_clarification[user_id] = {
                    "original_text": pending["original_text"],
                    "dish": dish,
                    "questions": questions,
                    "answers": [],
                    "current_index": 0,
                    "is_fix": False
                }
                await message.answer(f"Понял: {_esc(dish)}. {_esc(questions[0])}")
        else:
            await message.answer("Хорошо, тогда напиши, что выбрать из меню.")
        return

    if pending.get("precomputed") and text.strip().lower() in ("да", "ага", "угу", "верно", "всё верно", "все верно", "ок"):
        data = pending["precomputed"]
        _pending_clarification.pop(user_id, None)
        await _save_food_and_reply(message, user_id, data, fallback_dish=pending.get("dish", ""),
                                   today_str=today_str, is_fix=False)
        return

    if pending.get("is_fix"):
        _pending_clarification.pop(user_id, None)
        await message.answer("Секунду, смотрю...")

        ai_res = await _ai(ai.get_questions_for_ai, text)
        dish = ai_res.get("dish", text)
        questions = ai.ensure_questions(text, ai_res.get("questions", []))

        if not questions:
            food_data = await _ai(ai.calculate_nutrition, dish, text)
            if food_data and food_data.get('calories') is not None:
                await _save_food_and_reply(message, user_id, food_data, fallback_dish=dish, today_str=today_str, is_fix=True)
            else:
                await message.answer("Не смог посчитать. Попробуй написать вес (например 200 г).")
            return

        _pending_clarification[user_id] = {
            "original_text": text,
            "dish": dish,
            "questions": questions,
            "answers": [],
            "current_index": 0,
            "is_fix": True
        }
        await message.answer(f"Понял: {_esc(dish)}. {_esc(questions[0])}")
        return

    if pending.get("drink"):
        field = pending["fields"][pending["current_index"]]
        value = _parse_drink_answer(field, text, pending["kind"])
        pending["answers"].append(value)
        pending["current_index"] += 1

        if pending["current_index"] < len(pending["questions"]):
            _pending_clarification[user_id] = pending
            await message.answer(f"Понял. {_esc(pending['questions'][pending['current_index']])}")
            return

        _pending_clarification.pop(user_id, None)
        details = ", ".join([pending["original_text"]] + [a for a in pending["answers"] if a])
        await message.answer(f"Понял. Секунду, считаю «{_esc(pending['dish'])}»...")
        food_data = await _ai(ai.calculate_nutrition, pending["dish"], details)
        if not food_data or food_data.get("calories") is None:
            await message.answer("Не смог посчитать. Попробуй написать иначе.")
            return
        await _save_food_and_reply(message, user_id, food_data, fallback_dish=pending["dish"],
                                   today_str=today_str, is_fix=pending.get("is_fix", False))
        return

    answer = text.strip()

    # ответ про жирность приводим к числу: «один» -> «жирность 1%»
    cur_q = ""
    try:
        cur_q = pending["questions"][pending["current_index"]].lower()
    except Exception:
        cur_q = ""
    if "жирност" in cur_q:
        fat = _parse_fat(answer)
        grams_probe = re.search(r"(\d+(?:[.,]\d+)?)\s*(г|гр|грамм\w*|мл)", answer.lower())
        if (fat is not None and not grams_probe
                and not ai.has_portion(pending.get("original_text", ""))
                and not any(("мл" in q.lower() or "объ" in q.lower() or "скольк" in q.lower())
                            for q in pending["questions"][pending["current_index"] + 1:])):
            # человек назвал только жирность — объём спросим отдельным вопросом
            pending["questions"].append(ai.portion_question(pending.get("original_text", "")))
        if fat is not None:
            grams = re.search(r"(\d+(?:[.,]\d+)?)\s*(г|гр|грамм\w*|мл)", answer.lower())
            amount = f"вес {grams.group(1).replace(',', '.')} {grams.group(2)}" if grams else ""
            if grams:
                # «сметана 20» + «20 г, 15%»: убираем двусмысленное число из исходного текста
                num = grams.group(1).replace(",", ".")
                base = pending.get("original_text", "")
                cleaned = re.sub(r"\s*" + re.escape(num) + r"\s*$", "", base)
                if cleaned:
                    pending["original_text"] = cleaned
            fat_text = "обезжиренный (0%)" if fat == 0 else f"жирность {fat:g}%"
            answer = "; ".join(x for x in (amount, fat_text) if x)

    if answer.isdigit() and len(answer) <= 2:
        current_q = pending["questions"][pending["current_index"]].lower()
        if any(w in current_q for w in ("процент", "жирност", "грамм", "мл", "объем", "вес")):
            pass
        elif "штук" in current_q or "сколько" in current_q:
            pass
        else:
            await message.answer(f"Ты имеешь в виду {answer} штуки или {answer} грамма?")
            return

    if pending.get("sugar") and answer.lower().strip() in ("нет", "без", "ничего", "просто", "неа"):
        answer = "без сахара"

    if any(w in answer.lower() for w in ("не знаю", "незнаю", "как обычно", "на глаз")):
        answer = "стандарт"

    pending["answers"].append(answer)
    pending["current_index"] += 1

    if pending["current_index"] < len(pending["questions"]):
        q = pending["questions"][pending["current_index"]]
        _pending_clarification[user_id] = pending
        await message.answer(f"Понял. {_esc(q)}")
        return

    if pending.get("is_component"):
        dish = pending["dish"]
        parts = [pending.get("original_text", "")]
        if pending.get("portion"):
            parts.append(pending["portion"])
        details = ", ".join(parts + pending["answers"])
        await message.answer(f"Понял. Секунду, считаю «{_esc(dish)}»...")
        food_data = await _ai(ai.calculate_nutrition, dish, details)
        if not food_data or food_data.get('calories') is None:
            await message.answer(f"Не смог распознать КБЖУ для «{_esc(dish)}». Попробуй иначе.")
            _pending_clarification.pop(user_id, None)
            return
        acc = pending.get("accumulated", {})
        _merge_component(acc, food_data, dish)
        remaining = pending.get("remaining_components", [])
        _pending_clarification.pop(user_id, None)
        if remaining:
            next_comp = remaining[0]
            next_res = await _ai(ai.get_questions_for_ai, next_comp)
            next_dish = next_res.get("dish", next_comp)
            # один вопрос на компонент — иначе составное блюдо превращается в допрос
            next_q = ai.ensure_questions(next_comp, next_res.get("questions", []))[:1]
            if next_q:
                _pending_clarification[user_id] = {
                    "original_text": next_comp,
                    "dish": next_dish,
                    "questions": next_q,
                    "answers": [],
                    "current_index": 0,
                    "is_fix": False,
                    "is_component": True,
                    "remaining_components": remaining[1:],
                    "accumulated": acc
                }
                await message.answer(f"Понял: {_esc(next_dish)}. {_esc(next_q[0])}")
                return
            else:
                fd = await _ai(ai.calculate_nutrition, next_dish, next_comp)
                if fd and fd.get('calories') is not None:
                    _merge_component(acc, fd, next_dish)
        acc["dish"] = " + ".join(acc.get("dish", []))
        await _save_food_and_reply(message, user_id, acc, fallback_dish=acc["dish"], today_str=today_str, is_fix=False)
        return

    _pending_clarification.pop(user_id, None)
    dish = pending["dish"]
    parts = [pending.get("original_text", "")]
    if pending.get("portion"):
        parts.append(pending["portion"])
    details = ", ".join(parts + pending["answers"])
    used_standard = any(a.strip().lower() == "стандарт" for a in pending["answers"])
    if used_standard and not ai.has_portion(details):
        details += ", вес не указан — возьми средний показатель"
    if pending.get("sugar") and not re.search(r"\d+\s*мл|\d+\s*л\b|стакан", details):
        details += ", объём не указан — возьми стандартную порцию"
    is_fix = pending.get("is_fix", False)

    await message.answer(f"Понял. Секунду, считаю «{_esc(dish)}»...")
    food_data = await _ai(ai.calculate_nutrition, dish, details)

    if not food_data or food_data.get('calories') is None:
        await message.answer(f"Не смог распознать КБЖУ для «{_esc(dish)}». Попробуй иначе.")
        return
    await _save_food_and_reply(
        message, user_id, food_data, fallback_dish=dish, today_str=today_str, is_fix=is_fix,
        extra_note="Взял средний показатель." if used_standard else ""
    )

def _replace_cups(desc: str) -> str:
    """«Кружка с супом» → «Миска с супом»: суп и салат не пьют."""
    def rep(m):
        out = "миска" + (m.group(2) or "")
        return out[0].upper() + out[1:] if m.start() == 0 else out
    fixed = re.sub(r"\b(кружк\w*|чашк\w*|стакан\w*|бокал\w*)(\s+с\b)?", rep, desc, flags=re.IGNORECASE)
    return re.sub(r"миска\s+миска", "миска", fixed, flags=re.IGNORECASE)

async def _handle_photo(message, user_id, caption=None):
    await message.answer("Смотрю на фото...")
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    os.makedirs("downloads", exist_ok=True)
    file_path = f"downloads/{photo.file_id}.jpg"

    try:
        await bot.download_file(file.file_path, file_path)
        photo_result = await _ai(ai.analyze_photo, file_path)
    finally:
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except OSError: pass

    if photo_result and photo_result.get("error"):
        await message.answer("Не получилось посмотреть фото — сбой на моей стороне. Пришли его ещё раз или напиши текстом. 🐾")
        return

    if not photo_result or not photo_result.get("is_food"):
        await message.answer("Похоже, это не еда, но я могу ошибаться… Пришли другое фото или напиши текстом, что съел. 🐾")
        return

    desc = (photo_result.get("description") or "").strip()
    is_drink = bool(photo_result.get("is_drink"))
    if not is_drink and not re.search(
            r"чай|кофе|сок|напит|вод[аыу]|вино|пиво|компот|квас|кефир|молок|лимонад|кола",
            desc, re.IGNORECASE):
        # еда в глубокой посуде — всё равно тарелка/миска, а не кружка: иначе расчёт примет суп за напиток
        desc = _replace_cups(desc)
    name = (photo_result.get("name") or "").strip().rstrip(".") or desc
    confident = photo_result.get("confident", True)

    # Видит еду/напиток, но не может уверенно назвать — не угадываем, просим записать словами
    if not confident or not desc:
        if is_drink:
            await message.answer("Вижу напиток, но пока учусь его называть… Запиши, пожалуйста, что ты пил — например: капучино 200 мл. 💚")
        else:
            await message.answer("Вижу еду, но пока учусь её называть… Запиши, пожалуйста, что это — например: борщ 300 г. 💚")
        return

    # Уверенно увидел: сначала спрашиваем, верно ли название. Цифры — только после «да».
    _pending_clarification[user_id] = {
        "photo_confirm": True,
        "original_text": desc,
        "ask_text": name,
        "dish": name,
        "is_compound": bool(photo_result.get("is_compound")),
        "is_drink": is_drink,
        "questions": [],
        "answers": [],
        "current_index": 0,
        "is_fix": False,
    }
    await message.answer(f"Вижу: {_esc(name)}.\n\nВерно? Напиши «да» или «нет».")

async def _save_food_and_reply(message, user_id, food_data, fallback_dish, today_str, is_fix=False, extra_note=""):
    cal = food_data.get('calories', 0) or 0
    prot = food_data.get('protein', 0) or 0
    fat = food_data.get('fat', 0) or 0
    carb = food_data.get('carbs', 0) or 0
    weight = food_data.get('weight') or 100
    dish_name = food_data.get('dish') or fallback_dish

    if not dish_name:
        await message.answer("Похоже, это не еда.")
        return

    is_liquid = 1 if food_data.get('is_liquid') else 0
    ml = food_data.get('ml')
    salt = food_data.get('salt', 0) or 0

    try:
        if is_fix:
            database.update_last_food(
                user_id, today_str, dish_name, cal, prot, fat, carb,
                food_data.get('sugar', 0), food_data.get('bad_fat', 0), weight,
                is_liquid=is_liquid, ml=ml, salt=salt
            )
        else:
            database.add_food(
                user_id, today_str, dish_name, cal, prot, fat, carb,
                food_data.get('sugar', 0), food_data.get('bad_fat', 0), weight,
                is_liquid=is_liquid, ml=ml, salt=salt
            )
    except Exception:
        logger.exception("Ошибка сохранения еды (is_fix=%s)", is_fix)
        await message.answer("Не смог сохранить. Попробуй ещё раз.")
        return

    user = database.get_user(user_id)
    norms = _calc_norms(user)
    summary = database.get_day_summary(user_id, today_str)
    liquid_total = database.get_day_liquid(user_id, today_str)

    day_cal = int(summary['calories']) if summary else 0
    day_prot = summary['protein'] if summary else 0
    day_fat = summary['fat'] if summary else 0
    day_carb = summary['carbs'] if summary else 0

    action_word = "исправил" if is_fix else "записал"
    # если объём/вес уже есть в названии — не дублируем
    unit = "мл" if is_liquid else "г"
    weight_note = "" if (weight and str(int(weight)) in str(dish_name)) else f" ({weight} {unit})"
    reply_text = f"Отлично, {action_word}: {_esc(dish_name)}{weight_note}\n"
    reply_text += f"🔥 {cal} ккал | Б {prot} / Ж {fat} / У {carb}\n\n"

    if user.get('week', 1) == 1:
        reply_text += f"📊 <b>За сегодня:</b> {day_cal} ккал | Б {day_prot} / Ж {day_fat} / У {day_carb}\n"
        reply_text += f"💧 Жидкость: {liquid_total} мл"
    else:
        target_prot = norms['protein_high']
        target_water = norms['water_high']

        p_cal = _calc_percent_range(day_cal, norms['loss_low'], norms['loss_high'])
        p_prot = _calc_percent(day_prot, target_prot)
        p_water = _calc_percent(liquid_total, target_water)

        reply_text += f"📊 <b>За сегодня:</b> {day_cal} из {norms['loss_low']}–{norms['loss_high']} ккал ({p_cal}%)\n"
        reply_text += f"🥩 Белок: {day_prot} из {target_prot} г ({p_prot}%)\n"
        reply_text += f"💧 Жидкость: {liquid_total} из {target_water} мл ({p_water}%)"

    if "(среднее)" in dish_name or "(средняя" in dish_name or "стандарт" in dish_name.lower():
         reply_text += "\n\n<i>Взял средний показатель.</i>"
    elif extra_note:
        reply_text += f"\n\n<i>{extra_note}</i>"

    evening = _evening.get(user_id)
    if evening and evening.get("date") == today_str:
        phrases = evening.get("phrases") or list(EVENING_TOUCHES)
        evening["touches"] = evening.get("touches", 1) + 1
        if evening["touches"] <= 1 + len(phrases):
            reply_text += "\n\n<i>" + phrases[evening["touches"] - 2] + "</i>"
            _evening[user_id] = evening
        else:
            reply_text += "\n\n<i>" + EVENING_BYE + "</i>"
            _evening.pop(user_id, None)

    await message.answer(reply_text, reply_markup=_food_inline_keyboard())

async def _safe_ask_ai(question):
    try: return await _ai(ai.ask_ai_question, question)
    except Exception: logger.exception("Ошибка ai.ask_ai_question"); return None

def _parse_weight(text):
    try: return float(text.strip().replace(",", "."))
    except ValueError: return None

async def main():
    database.init_db()
    logger.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
