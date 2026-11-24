import os
import json
import re
import base64
import logging
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Модель для текста и модель для картинок РАЗНЫЕ.
# Картинки у DeepSeek понимает только deepseek-flash (deepseek-chat их не принимает).
TEXT_MODEL = os.getenv("DEEPSEEK_TEXT_MODEL", "deepseek-chat")
VISION_MODEL = os.getenv("DEEPSEEK_VISION_MODEL", "deepseek-flash")

if not DEEPSEEK_API_KEY:
    raise RuntimeError(
        "Не задан DEEPSEEK_API_KEY. Положи ключ в файл .env рядом с ботом: "
        "DEEPSEEK_API_KEY=sk-..."
    )

# timeout спасает от вечного ожидания, max_retries — от случайных сетевых сбоев
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    timeout=60.0,
    max_retries=2,
)


# ============================================================
# СПРАВОЧНИК СТАНДАРТОВ «НЕ ЗНАЮ»
# ============================================================
STANDARDS = {
    "кола": 330, "сок": 330, "пиво": 500, "вино": 150, "крепкое": 50,
    "вода": 250, "кофе": 250, "чай": 250, "смузи": 250, "кисель": 250,
    "йогурт": 125, "творог": 150, "кефир": 250, "молоко": 250, "сметана": 30,
    "сыр": 50, "колбаса": 30, "рыба": 150, "мясо": 150, "курица": 150,
    "шашлык": 200, "стейк": 200, "отбивная": 150, "гуляш": 200,
    "курица в блюде": 100, "холодец": 200,
    "гречка": 200, "рис": 200, "макароны": 200, "картофель": 200,
    "пюре": 200, "овощи": 200, "салат": 150,
    "сосиска": 50, "сосиска в тесте": 120, "яйцо": 55, "пельмень": 12,
    "блин": 50, "котлета": 80, "конфета": 10, "эклер": 75,
    "суп": 300, "борщ": 300, "щи": 300, "окрошка": 300, "каша": 250,
    "пирожное": 100, "торт": 100, "составное": 300,
    "капучино": 200, "латте": 300, "раф": 300, "американо": 200,
    "эспрессо": 30, "какао": 300, "бабл ти": 400,
}

# Размеры для штучных (если «не знаю» про размер)
SIZE_MIDDLE = {
    "банан": 100, "яблоко": 150, "груша": 140, "апельсин": 180,
    "мандарин": 70, "киви": 75, "персик": 120, "слива": 40,
    "абрикос": 40, "гранат": 200, "хурма": 150, "авокадо": 150,
    "огурец": 100, "помидор": 100, "перец болгарский": 120,
    "морковь": 80, "свёкла": 100, "картофелина": 100, "кабачок": 200,
    "баклажан": 200, "клубника": 15, "черешня": 8, "виноград": 5,
}


SYSTEM_BASE = """Ты — Добрый Кот, помощник по питанию GOODKAT AI.
Характер: тёплый, спокойный, без стыда, запретов и морализаторства. Принцип: честность важнее утешения.
Общие правила для всех ответов:
- Отвечай по-русски, кратко и по делу.
- Разметка: только HTML-теги <b> и <i>. Никакого Markdown (**, #).
- Не выдумывай данные: если чего-то не видно или не сказано — прямо скажи об этом.
- Числовые поля отдавай числами, без слов и единиц измерения.
- Не задавай больше одного уточняющего вопроса за раз."""


def standard_portion(dish: str) -> str:
    """Подсказка для ИИ, когда человек ответил «не знаю».

    Раньше словари STANDARDS/SIZE_MIDDLE лежали в файле мёртвым грузом:
    ответ «не знаю» превращался в слово «стандарт», и ИИ просто угадывал.
    Теперь мы подставляем реальный вес из справочника.
    """
    low = (dish or "").lower().replace("ё", "е")
    for name in sorted(list(STANDARDS) + list(SIZE_MIDDLE), key=len, reverse=True):
        key = name.replace("ё", "е")
        if key in low:
            if name in STANDARDS:
                return f"стандартная порция {STANDARDS[name]} г (или {STANDARDS[name]} мл, если это напиток)"
            return f"одна штука среднего размера, примерно {SIZE_MIDDLE[name]} г"
    return "стандартная порция примерно 250-300 г"


# ============================================================
# БАЗОВЫЕ ПРАВИЛА (для финального подсчета)
# ============================================================
FOOD_RULES = """ВАЖНЫЕ ПРАВИЛА ОЦЕНКИ (Следуй строго!):
1. СУПЫ: Гороховый 65 ккал/100г, Борщ 45, Рассольник 55, Куриный бульон 20, Крем-суп 60. Окрошка: на квасе 55, на кефире 75, на майонезе 130. Если просто "суп" — 70 ккал. НЕ ЗАВЫШАЙ.
2. САХАР: В поле "sugar" пиши ТОЛЬКО ДОБАВЛЕННЫЙ сахар (десерты, газировка). Природный (фрукты, молоко) — 0.
3. ШТУЧНЫЕ ПРОДУКТЫ: Вес за штуку: яйцо 55г, сосиска 50г, пельмень 12г, блин 50г, котлета 80г, конфета 10г, эклер 75г.
4. ЖИДКОСТЬ vs ЕДА: Всё, что пьют — is_liquid=true, ml=объем. Жидкая еда ложкой (суп, каша) — is_liquid=false, ml=null.
5. СЛОВА-МЕРЫ: Стакан 250, Чашка 200, Кружка 300, Рюмка 50, Стопка 100, Бокал 150, Чекушка 250.
6. ОТРИЦАНИЯ: "без сахара", "без масла" — убери этот компонент из расчёта.
7. ЧИСЛА ЧЕРЕЗ ЗАПЯТУЮ: "кефир 2,5" — это ЖИРНОСТЬ.
8. ЕСЛИ ДАННЫХ НЕТ (перевёрнутая упаковка, нечитаемое меню, закрытая страница) — честно скажи, что не видно, и посчитай по типичному значению, но пометь в названии "(примерно)".
9. КОФЕ С МОЛОКОМ без уточнений — обычное молоко 2,5%. Сахар в напитке — 0, если не сказано обратное.
10. САХАР В НАПИТКЕ: 1 чайная ложка = 6 г = 24 ккал, 2 ложки = 12 г = 48 ккал. Если указано в граммах — считай по 4 ккал на грамм.
11. КОМПОТ / МОРС / КИСЕЛЬ: база без сахара ~20 ккал/100 мл (250 мл = 50 ккал). Добавленный сахар прибавляй сверху по 4 ккал на грамм.
12. СОК: свежевыжатый ~45 ккал/100 мл, пакетированный ~50 ккал/100 мл (250 мл = 112 и 125 ккал).
13. КОЛА обычная 42 ккал/100 мл (330 мл = 139 ккал), Zero — 0.
18. Вино считай по типу: сухое красное/белое 70-75 ккал на 100 мл, полусухое 75-85, полусладкое 90-100, сладкое и десертное 150-160, креплёное (портвейн, кагор) 160-170, шампанское брют 70-80, глинтвейн 110-130. Если тип не назван — не бери среднее, а спроси.
17. Смешанные напитки считай целиком по объёму: «виски с колой 250 мл» — это примерно 50 мл виски (40%) + 200 мл колы: с обычной колой ~200 ккал, с Zero ~115 ккал. «Джин с тоником 250 мл» — 50 мл джина + 200 мл тоника: обычный ~180 ккал, лайт ~120. Водка с колой, ром с колой — та же логика. Сахар в напитке указывай отдельно (г).
14. МОЛОЧНЫЕ ПРОДУКТЫ (кефир, молоко, творог, сметана, йогурт, ряженка, айран, простокваша, сливки, сыр) — жирность ОБЯЗАТЕЛЬНО уточняй, если человек её не назвал: разница между 1% и 9% огромная. Не подставляй 2,5% молча.
   Если жирность так и не названа — считай по 2,5% и пометь это в названии: КЕФИР и МОЛОКО без указания жирности — 2,5% (кефир 53 ккал/100 мл, молоко 52 ккал/100 мл). 1% — 40 ккал/100 мл, 3,2% — 59. Не занижай до обезжиренного.
15. МЯСО И РЫБА (на 100 г): куриная грудка сырая 110 / варёная 150 / жареная 165; свинина сырая 260 / жареная 320; говядина сырая 190 / варёная 250; шашлык свиной готовый 300-320; рыба сырая 90-120 / жареная 160-200 / на пару 120.
   Если вес назван как сырой — считай по сырому продукту и напиши в названии «(сырое)».
   ВАЖНО: «мясо по-французски», «свинина по-французски», «курица по-французски» — это НЕ просто мясо,
   а запечённое блюдо с луком, сыром и майонезом: 250-300 ккал на 100 г (курица — 200-230).
   «Мясо по-домашнему» — тушёное с картофелем, 180-220 ккал/100 г. «Котлета по-киевски» — 300-330 ккал/100 г.
   Считай блюдо целиком, а не ингредиент по названию.
   Если вес назван человеком — не пиши «стандартная порция», просто блюдо и граммы.
16. В деталях может быть «вес 20 г; жирность 15%» — это РАЗНЫЕ числа. Граммы идут в weight, проценты — в калорийность и в название («Сметана 15%»). Не путай вес с жирностью и не подставляй вместо них друг друга.
"""


def _extract_json(content: str):
    """Достаём JSON из ответа модели.

    Модель может обернуть ответ в ```json ... ``` или добавить текст вокруг.
    Старый вариант (find("{") ... rfind("}")) ломался, если в ответе два
    объекта или фигурная скобка внутри текста.
    """
    if not content:
        return None

    text = content.strip()

    # 1) ответ в markdown-ограждении
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    # 2) целиком как JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3) первый сбалансированный объект
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)

    logger.warning("Не удалось распарсить JSON | сырой ответ: %r", content[:200])
    return None


def _ask(prompt: str, *, temperature: float = 0.1, json_mode: bool = False,
         model: str | None = None, max_tokens: int = 1500,
         system: str | None = SYSTEM_BASE) -> str | None:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    kwargs = {
        "model": model or TEXT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # У DeepSeek размышление включено по умолчанию: модель тратит лимит ответа
        # на «думанье», а сам ответ обрезается или приходит пустым. Нам нужен
        # короткий готовый результат, поэтому размышление выключаем.
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


# ============================================================
# 1. КОНСУЛЬТАНТ: Что нам нужно спросить у человека?
# ============================================================
_PORTION_RE = re.compile(
    r"\d+\s*(?:г|гр|грамм\w*|мл|л|литр\w*|шт|штук\w*)\b"
    r"|\b\d{2,}\b"
    r"|стакан|чашк|кружк|бокал|тарелк|порци|ломт|кусок|ложк|половин|пол-?литра",
    re.IGNORECASE,
)
_LIQUID_HINTS = (
    "кефир", "молоко", "вода", "сок", "компот", "морс", "кисель", "чай", "кофе",
    "капучино", "латте", "раф", "американо", "эспрессо", "кола", "пепси", "фанта",
    "спрайт", "квас", "пиво", "вино", "виски", "коньяк", "водка", "лимонад",
    "энергетик", "смузи", "айран", "ряженка", "простокваша",
)
_PIECE_HINTS = ("яйц", "банан", "яблок", "апельсин", "мандарин", "груш", "персик",
                "помидор", "огурец", "конфет", "печень", "хлеб", "тост", "сырник", "блин")


_PORTION_UNIT_RE = re.compile(
    r"\d+\s*(?:г|гр|грамм\w*|мл|л|литр\w*|шт|штук\w*)\b"
    r"|стакан|чашк|кружк|бокал|тарелк|порци|ломт|кусок|ложк|половин|пол-?литра",
    re.IGNORECASE,
)


def has_portion(text: str) -> bool:
    """Назван ли вес/объём. «2,5» и «1%» — жирность, а не количество; «20» без единиц — тоже нет."""
    low = (text or "").lower().replace("ё", "е")
    cleaned = re.sub(r"\d+[.,]\d+\s*%?", " ", low)
    cleaned = re.sub(r"\d+\s*%", " ", cleaned)
    if _PORTION_UNIT_RE.search(cleaned):
        return True
    bare = re.search(r"\b(\d{2,4})\b", cleaned)
    return bool(bare and int(bare.group(1)) >= 30)


def portion_question(text: str) -> str:
    low = (text or "").lower().replace("ё", "е")
    if any(w in low for w in _LIQUID_HINTS):
        return "Сколько примерно мл?"
    if any(w in low for w in _PIECE_HINTS):
        return "Сколько штук?"
    return "Сколько примерно грамм?"


_WEIGHT_Q = re.compile(r"скольк\w*.*(грамм|мл|порци|вес)|(грамм|мл|порци)\w*.*скольк", re.IGNORECASE)


_MEAT_FISH = (
    "мясо", "говядин", "свинин", "курин", "куриц", "индейк", "баранин", "телятин",
    "шашлык", "стейк", "гуляш", "отбивн", "котлет", "рыб", "лосос", "треск", "минтай",
    "форел", "скумбр", "сельд", "тунец", "карп", "судак", "креветк", "кальмар",
)
_COOKED_WORDS = (
    "сыро", "жарен", "жарк", "варен", "отвар", "пар", "запеч", "тушен", "тушён",
    "грил", "копч", "готов", "припущ", "на гриле",
)
WINE_STEMS = ("вин", "шампанск", "просекко", "игрист", "портвейн", "кагор", "сангри")
WINE_QUESTION = "Какое вино — сухое, полусухое или сладкое (десертное)?"


def needs_wine_question(text: str, questions: list) -> bool:
    """Сухое вино 70 ккал/100 мл, сладкое — 150+: спрашиваем, какое."""
    low = (text or "").lower().replace("ё", "е")
    if not any(w in low for w in ("шампанск", "просекко", "игрист", "портвейн", "кагор", "сангри")):
        if not re.search(r"(?<![а-яё])вин(о|а|ом|е|у)?(?![а-яё])", low):
            return False
    if any(w in low for w in ("сух", "полусух", "сладк", "брют", "крепл", "десертн", "полусладк")):
        return False
    return not any("вино" in q.lower() for q in (questions or []))


RECIPE_MARKERS = (
    "по-французски", "по французски", "по-домашнему", "по домашнему", "по-киевски", "по киевски",
    "по-гавайски", "по-тайски", "по-мексикански", "по-гречески", "по-деревенски",
    "карбонара", "болоньезе", "оливье", "цезарь", "под шубой", "жульен", "жюльен",
    "гавайск", "терiyaki", "терияки",
)
RECIPE_QUESTION = "Это запечённое блюдо с сыром и майонезом или без? (обычно «по-французски» — с ними)"

COOKING_QUESTION = "Как приготовлено — сырое, варёное, на пару, жареное или запечённое?"


_DAIRY_FAT = (
    "кефир", "молоко", "творог", "сметана", "йогурт", "ряженка", "айран", "простокваша",
    "сливки", "сыр", "мацони", "тан", "катык", "снежок", "сгущенк", "творожный сыр",
)
FAT_QUESTION = "Какая жирность — например 1%, 2,5%, 3,2% или 5%?"
PORTION_AND_FAT_QUESTION = "Сколько грамм и какая жирность? Например: «200 г, 2,5%»"
PORTION_AND_FAT_QUESTION_LIQUID = "Сколько миллилитров и какая жирность? Например: «250 мл, 4%»"


def needs_fat_question(text: str, questions: list) -> bool:
    """Молочные продукты: жирность сильно меняет калории — спрашиваем, если не названа."""
    low = (text or "").lower().replace("ё", "е")
    if not any(w in low for w in _DAIRY_FAT):
        return False
    if "%" in low or "жирност" in low or "обезжир" in low or "нулевк" in low:
        return False
    # «кефир 2,5» — число с запятой от 1 до 20 это уже жирность, а не объём
    dec = re.search(r"(?<!\d)(\d{1,2})[.,](\d)(?!\d)", low)
    if dec and 1 <= float(dec.group(1) + "." + dec.group(2)) <= 20:
        return False
    return not any("жирност" in q.lower() for q in (questions or []))


MAYO_CHEESE_MARKERS = (
    "по-французски", "по французски", "жюльен", "жульен", "по-гавайски", "гавайск", "под шубой",
)


def needs_recipe_question(text: str, questions: list) -> bool:
    """«Мясо по-французски» — это рецепт, а не кусок мяса: спрашиваем про сыр и майонез."""
    low = (text or "").lower().replace("ё", "е")
    if not any(m in low for m in MAYO_CHEESE_MARKERS):
        return False
    if any(w in low for w in ("майонез", "без майонеза", "сметан", "без сыра", "с сыром", "без соуса")):
        return False
    return True


def needs_cooking_question(text: str, questions: list) -> bool:
    """Мясо и рыба: способ приготовления меняет калории в 1,5-2 раза — спрашиваем всегда."""
    low = (text or "").lower().replace("ё", "е")
    if not any(w in low for w in _MEAT_FISH):
        return False
    if any(w in low for w in _COOKED_WORDS):
        return False
    return not any("приготов" in q.lower() for q in (questions or []))


def ensure_questions(text: str, questions: list) -> list:
    """Если количество не названо — вопрос про порцию обязателен. Максимум три."""
    questions = [str(q) for q in (questions or [])][:3]
    if has_portion(text):
        # вес уже назван — про количество не переспрашиваем и не ставим его первым
        questions = [q for q in questions if not _WEIGHT_Q.search(q)]
    else:
        # вопрос про количество ставим первым — человек ещё помнит, сколько съел
        for i, q in enumerate(questions):
            if "скольк" in q.lower():
                if "жирност" in q.lower():
                    questions = [q] + questions[:i] + questions[i + 1:]
                else:
                    # у модели может быть «грамм» вместо «мл» — ставим правильные единицы
                    rest = [x for j, x in enumerate(questions) if j != i]
                    questions = [portion_question(text)] + rest
                break
        else:
            questions = [portion_question(text)] + questions

    recipe = needs_recipe_question(text, questions)
    # рецептные блюда и так запечённые — вопрос про способ приготовления им не нужен
    if not recipe and needs_cooking_question(text, questions) and len(questions) < 3:
        questions = questions + [COOKING_QUESTION]
    if recipe:
        # блюдо уже готовое и запечённое — вопрос «сырое или готовое» лишний
        questions = [q for q in questions if not re.search(r"сырое|готов", q, re.IGNORECASE)]
        already = any("майонез" in q.lower() or "с сыром" in q.lower() or "сыра" in q.lower()
                      for q in questions)
        if not already and len(questions) < 3:
            questions = questions + [RECIPE_QUESTION]

    if needs_wine_question(text, questions) and len(questions) < 3:
        questions = questions + [WINE_QUESTION]

    if needs_fat_question(text, questions):
        if has_portion(text):
            if len(questions) < 3:
                questions = questions + [FAT_QUESTION]
        else:
            # «сметана 20» — 20 это граммы или проценты? спрашиваем про оба числа сразу
            questions = [q for q in questions if not _WEIGHT_Q.search(q) and "скольк" not in q.lower()]
            liquid = any(w in (text or "").lower().replace("ё", "е") for w in _LIQUID_HINTS)
            questions = [PORTION_AND_FAT_QUESTION_LIQUID if liquid else PORTION_AND_FAT_QUESTION] + questions
    return questions[:3]


def get_questions_for_ai(user_text: str) -> dict:
    prompt = f"""Ты — умный помощник по питанию. Пользователь написал: "{user_text}".
Твоя задача — понять, хватает ли данных, чтобы посчитать КБЖУ, или нужно задать уточняющие вопросы.

ПРАВИЛА:
1. Если это составное блюдо (пюре с гуляшом, гречка с курицей) — разбей на компоненты.
2. Если количество уже есть (300, 300 г, 0,5 л, 2 штуки, стакан) — про вес и объём НЕ спрашивай.
3. Если чего-то важного не хватает — задай ДО ТРЁХ вопросов. Каждый вопрос — про ОДИН факт, который реально меняет калории, и сразу с вариантами в скобках.
   Порядок важности: состав/мясо → способ приготовления → жирность/молоко → сахар/соус → объём.
   ДЛЯ МЯСА, ПТИЦЫ, РЫБЫ И БЛЮД ИЗ НИХ способ приготовления обязателен, даже если вес назван:
   сырое / варёное / на пару / жареное / запечённое — это разница в 1,5-2 раза.
   Если человек назвал вес, но не сказал, сырой он или готовый, уточни: «Это вес сырого мяса или готового блюда?».
   Сырой вес даёт меньше калорий на грамм, готовый — больше (вода выпарилась).
   Примеры хороших вопросов: «Из какого мяса и как приготовлена (курица / свинина; жареная / на пару)?», «На молоке или на воде?», «С майонезом или без?», «Какая жирность (1% / 2,5% / 3,2%)?»
4. Однозначные блюда — вопросов про СОСТАВ нет: борщ, щи, окрошка, гречка, рис, макароны, яблоко, банан, апельсин, яйцо, хлеб, вода, пиво, вино. «гречка 200» и «борщ 300» — сразу считай.
   НО: если количество (граммы, мл, штуки) не названо — вопрос про порцию обязателен, даже для однозначных блюд. «кефир» → «Сколько примерно мл?», «котлета» → «Сколько примерно грамм?». Никогда не подставляй стандартную порцию молча.
5. НИКОГДА не спрашивай то, что не меняет КБЖУ: калибр яйца, «вкрутую или всмятку», сорт чая, пропорции пенки, «мл или граммы».
6. Вопросы бот задаст по очереди, по одному. Три — предел. Если сомневаешься, нужен ли вопрос — не задавай.
5. Если человек назвал вид («борщ», а не «суп») — не спрашивай «какой суп».
6. По умолчанию: кофе с молоком — обычное молоко 2,5%; сахар в напитках — 0, если не сказано обратное; яйцо 55 г, банан 120 г, сосиска 50 г, котлета 80 г, пельмень 12 г, блин 50 г.
7. Если всё понятно — верни пустой список вопросов. Пустой список лучше лишнего вопроса.

Отвечай СТРОГО в формате JSON:
{{
  "dish": "название блюда (как написал пользователь)",
  "questions": ["вопрос 1", "вопрос 2"]
}}
Если вопросов нет, верни: {{"dish": "название", "questions": []}}"""

    try:
        content = _ask(prompt, json_mode=True)
        result = _extract_json(content)

        if not isinstance(result, dict) or "dish" not in result or "questions" not in result:
            return {"dish": user_text, "questions": ["Сколько примерно грамм?"]}

        result["questions"] = [str(q) for q in (result.get("questions") or [])][:3]
        return result
    except Exception as e:
        logger.exception("Ошибка ИИ (get_questions): %s", e)
        return {"dish": user_text, "questions": ["Сколько примерно грамм?"]}


# ============================================================
# 1.1 РАЗБИВКА НА КОМПОНЕНТЫ (для составных блюд)
# ============================================================
def split_components(user_text: str) -> list:
    if not user_text:
        return []
    prompt = f"""Пользователь написал: "{user_text}".
Разбей это на отдельные компоненты (блюда/продукты). Если блюдо одно — верни список из одного элемента.
Примеры:
- "пюре с котлетой и салат из огурцов" -> ["пюре", "котлета", "салат из огурцов"]
- "борщ 300" -> ["борщ 300"]
- "гречка с курицей" -> ["гречка", "курица"]

Отвечай СТРОГО в формате JSON:
{{"components": ["компонент 1", "компонент 2"]}}"""

    try:
        content = _ask(prompt, json_mode=True)
        result = _extract_json(content)
        if isinstance(result, dict) and isinstance(result.get("components"), list):
            parts = [str(x) for x in result["components"] if x]
            return parts or [user_text]
        return [user_text]
    except Exception as e:
        logger.exception("Ошибка ИИ (split_components): %s", e)
        return [user_text]


# ============================================================
# 2. СЧЕТЧИК: Финальный подсчет КБЖУ
# ============================================================
def _explicit_amount(text: str):
    """Явно названное количество: «150 г», «250 мл», «300». Жирность («2,5») не в счёт."""
    low = (text or "").lower()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(мл)\b", low)
    if m:
        return float(m.group(1).replace(",", ".")), "мл"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(г|гр|грамм\w*)\b", low)
    if m:
        return float(m.group(1).replace(",", ".")), "г"
    # без единиц весом считаем только правдоподобное количество (не «2 яйца»)
    m = re.search(r"\b(\d{2,4})\b", low)
    if m and int(m.group(1)) >= 30:
        return float(m.group(1)), None
    return None, None


def calculate_nutrition(dish_name: str, details: str) -> dict:
    standard_hint = ""
    if "стандарт" in (details or "").lower():
        standard_hint = f"\nСправочная порция для этого блюда: {standard_portion(dish_name)}. Используй её.\n"

    prompt = f"""Ты — нутрициолог. Блюдо: "{dish_name}".
Собранные уточнения от пользователя: "{details}".{standard_hint}

Посчитай итоговые КБЖУ на основе этих данных.
{FOOD_RULES}

Отвечай СТРОГО в формате JSON, все числовые поля — ЧИСЛАМИ (без слов и единиц):
{{
  "dish": "красивое название блюда",
  "weight": 300,
  "calories": 450,
  "protein": 15,
  "fat": 20,
  "carbs": 45,
  "sugar": 0,
  "bad_fat": 0,
  "salt": 1,
  "is_liquid": false,
  "ml": null
}}"""

    try:
        content = _ask(prompt, json_mode=True)
        data = _extract_json(content)
        if not isinstance(data, dict):
            return None
        result = _coerce_nutrition(data)

        # ИИ иногда «забывает» названный вес: приводим к тому, что сказал человек
        amount, unit = _explicit_amount(details)
        weight = result.get("weight")
        if amount and weight and float(weight) > 0 and abs(float(weight) - amount) > 1:
            k = amount / float(weight)
            for f in ("calories", "protein", "fat", "carbs", "sugar", "bad_fat", "salt"):
                if result.get(f) is not None:
                    result[f] = round(float(result[f]) * k, 1)
            result["weight"] = amount
        if result.get("is_liquid") and unit == "мл" and amount:
            result["ml"] = int(round(amount))
        return result
    except Exception as e:
        logger.exception("Ошибка ИИ (calculate_nutrition): %s", e)
        return None


_NUM_FIELDS = ("weight", "calories", "protein", "fat", "carbs", "sugar", "bad_fat", "salt")


def _coerce_nutrition(data: dict) -> dict:
    """Приводим числа к float/int.

    ИИ иногда возвращает "450", "450 ккал", "~30 г". Раньше такие значения
    попадали в базу как текст, и SUM() молча превращал их в 0 — запись есть,
    а в итоге дня её нет.
    """
    out = dict(data)
    for field in _NUM_FIELDS:
        value = out.get(field)
        if value is None or value == "":
            out[field] = 0
            continue
        if isinstance(value, (int, float)):
            out[field] = value
            continue
        match = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
        out[field] = float(match.group(0).replace(",", ".")) if match else 0

    out["calories"] = int(round(out["calories"]))
    out["weight"] = out["weight"] or 100

    ml = out.get("ml")
    if ml not in (None, ""):
        match = re.search(r"-?\d+(?:[.,]\d+)?", str(ml))
        out["ml"] = int(float(match.group(0).replace(",", "."))) if match else None
    else:
        out["ml"] = None

    liquid = out.get("is_liquid")
    if isinstance(liquid, str):
        liquid = liquid.strip().lower() in ("true", "1", "да", "yes")
    out["is_liquid"] = bool(liquid)
    return out


# ============================================================
# 3. ФОТО: Распознавание и черновик
# ============================================================
def _shrink_image(file_path: str, max_side: int = 1280, quality: int = 85):
    """Уменьшаем фото до 1280 px по длинной стороне.

    Telegram отдаёт снимки с телефона на 2-4 МБ. Для чтения этикетки и оценки
    порции хватает 1280 px: загрузка быстрее, токенов меньше, качество не страдает.
    Возвращает (путь, mime, создан_ли_временный_файл).
    """
    try:
        from PIL import Image
    except ImportError:
        return file_path, _guess_mime(file_path), False

    try:
        size = os.path.getsize(file_path)
        with Image.open(file_path) as img:
            width, height = img.size
            if max(width, height) <= max_side and size <= 400 * 1024:
                return file_path, "image/jpeg", False
            ratio = max_side / max(width, height)
            if ratio < 1:
                img = img.resize((int(width * ratio), int(height * ratio)), Image.LANCZOS)
            out_path = file_path + ".small.jpg"
            img.convert("RGB").save(out_path, "JPEG", quality=quality, optimize=True)
            return out_path, "image/jpeg", True
    except Exception:
        logger.warning("Не удалось сжать фото, отправляю как есть", exc_info=True)
        return file_path, _guess_mime(file_path), False


def _image_message(file_path: str, text_prompt: str, media_type: str | None = None):
    file_path, media_type, temp = _shrink_image(file_path)
    try:
        with open(file_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
    finally:
        if temp and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text_prompt},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded_string}"}},
            ],
        }
    ]


def _guess_mime(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    return {
        ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    }.get(ext, "image/jpeg")


def analyze_photo(file_path):
    try:
        messages = _image_message(file_path, (
            "Посмотри на фото. Если это упаковка с составом — выпиши КБЖУ на 100г и общий вес.\n"
            "Если это еда или напиток — назови, что это, как назвал бы человек.\n"
            "ВАЖНО: Описывай ТОЛЬКО еду/напиток и посуду, в которой они находятся. Никакой обстановки, фона, скатертей, салфеток, столов, пакетиков рядом.\n"
            "ВАЖНО ПРО ПОСУДУ: суп, пюре, салат, второе блюдо лежат в тарелке или миске. Кружка, стакан и бокал — только для напитков. Не называй тарелку или миску кружкой. Пример: 'Тарелка с супом-пюре', 'Миска с салатом', 'Кружка с чаем'.\n"
            "Определи, это одно простое блюдо (яблоко, тарелка супа) или сложный поднос/составное блюдо (картошка с котлетой, несколько тарелок).\n"
            "Если видишь еду или напиток, но не можешь уверенно назвать, что именно — поставь 'уверенность: нет'. Не угадывай название напитка: пиво, квас и коктейль по фото не различить.\n"
            "Формат ответа (строго):\n"
            "еда: да или нет\n"
            "напиток: да или нет\n"
            "составное: да или нет\n"
            "уверенность: да или нет\n"
            "название: коротко, 2-4 слова, только еда или напиток, без посуды (например: Борщ; Куриная грудка с рисом; Капучино)\n"
            "описание: краткое описание (перечисли всё, что видишь)\n"
        ))

        content = _ask_messages(messages)
        logger.info("Модель увидела: %s", content)

        is_food = False
        is_compound = False
        is_drink = False
        drink_seen = False
        confident = True
        name = ""
        description = ""

        for line in content.splitlines():
            line = line.strip()
            low = line.lower()
            if low.startswith("еда:"):
                is_food = low.split(":", 1)[1].strip().startswith("да")
            elif low.startswith("напиток:") or low.startswith("напитки:"):
                drink_seen = True
                is_drink = low.split(":", 1)[1].strip().startswith("да")
            elif low.startswith("составное:"):
                is_compound = low.split(":", 1)[1].strip().startswith("да")
            elif low.startswith("уверенность:"):
                confident = not low.split(":", 1)[1].strip().startswith("нет")
            elif low.startswith("название:"):
                name = line.split(":", 1)[1].strip().strip("«»\"")
            elif low.startswith("описание:"):
                description = line.split(":", 1)[1].strip()

        if not description:
            confident = False
        if not drink_seen and description:
            # старая модель могла не прислать строку «напиток» — понимаем по посуде
            low_desc = description.lower()
            is_drink = any(w in low_desc for w in ("кружка", "стакан", "бокал", "чашка", "бутылка"))

        if not name:
            name = description.split("(")[0].strip().rstrip(".")
        return {"is_food": is_food, "is_compound": is_compound, "is_drink": is_drink,
                "confident": confident, "name": name, "description": description, "error": False}
    except Exception as e:
        # Раньше любая ошибка API выглядела как «это не еда» — человек думал,
        # что бот не признал еду. Теперь ошибка отличается от «не еда».
        logger.exception("Ошибка ИИ (analyze_photo): %s", e)
        return {"is_food": False, "is_compound": False, "description": "", "error": True}


def _ask_messages(messages, *, temperature: float = 0.1, max_tokens: int = 900) -> str:
    if not messages or messages[0].get("role") != "system":
        messages = [{"role": "system", "content": SYSTEM_BASE}] + messages
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return response.choices[0].message.content or ""


# ============================================================
# 3.1 ФОТО МЕНЮ: Распознавание списка блюд
# ============================================================
def analyze_menu_photo(file_path):
    try:
        messages = _image_message(file_path, (
            "Посмотри на фото. Это может быть меню кафе или ресторана.\n"
            "Если это меню — выпиши ВСЕ блюда и напитки, которые видишь, списком. Каждое с новой строки. Не пропускай позиции. Если есть цены — не пиши их, только названия блюд.\n"
            "Если это не меню, а еда — опиши, что видно.\n"
            "Формат ответа (строго):\n"
            "меню: да или нет\n"
            "описание: список блюд через запятую или краткое описание еды\n"
        ))

        content = _ask_messages(messages, max_tokens=1200)
        logger.info("Модель увидела меню: %s", content)

        is_menu = False
        description = ""
        for line in content.splitlines():
            line = line.strip()
            low = line.lower()
            if low.startswith("меню:"):
                is_menu = low.split(":", 1)[1].strip().startswith("да")
            elif low.startswith("название:"):
                name = line.split(":", 1)[1].strip().strip("«»\"")
            elif low.startswith("описание:"):
                description = line.split(":", 1)[1].strip()

        return {"is_menu": is_menu, "description": description, "error": False}
    except Exception as e:
        logger.exception("Ошибка ИИ (analyze_menu_photo): %s", e)
        return {"is_menu": False, "description": "", "error": True}


# ============================================================
# 4. ВОПРОС-ОТВЕТ (Помощь)
# ============================================================
def ask_ai_question(question):
    prompt = f"""Ты — Добрый Кот, помощник по питанию и похудению в духе бережного отношения к еде (без стыда и запретов).
Пользователь спрашивает: "{question}".

ТВОИ ПРАВИЛА:
1. Отвечай ТОЛЬКО на вопросы про еду, калории, питание, похудение и пищевые привычки.
   Если вопрос не по теме — ответь ровно одну фразу: "Я помогаю только с питанием и движением. Давайте вернёмся к еде."
2. Отвечай кратко, тепло и по делу. Без лекций и морализаторства.
3. Если пользователь говорит, что ОЧЕНЬ ХОЧЕТ вредную еду — НЕ запрещай. Скажи, что это можно, назови калорийность, предложи съесть половину или альтернативу.
4. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО добавлять в конце ответа любые предложения что-то сделать, встречные вопросы или призывы к действию. Ответ должен быть СТРОГО КОНЕЧНЫМ: просто ответ на вопрос и всё. Никаких "хочешь, посчитаю?", "может, составим меню?", "давай определим вес?" и подобного.

5. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать один и тот же шаблон ответа. Каждый раз выбирай ОДИН РАЗНЫЙ подход из списка:
   - Подход 1 (Состав): Расскажи, из чего состоит блюдо и как это влияет на организм.
   - Подход 2 (Альтернатива): Предложи, чем можно заменить это блюдо, чтобы получить похожее удовольствие, но с меньшими калориями.
   - Подход 3 (Баланс): Скажи, как вписать это блюдо в текущий день.
   - Подход 4 (Психология/Пауза): Мягко предложи подождать 10-15 минут, выпить воды или переключиться на другое занятие.
   - Подход 5 (Осознанность): Спроси, чего именно хочется (сладкого, соленого, хрустящего) и предложи варианты под этот вкус.

6. Разметка: только теги <b> и <i>. Никакого Markdown (** и #).

Отвечай по-русски."""

    try:
        return _ask(prompt, temperature=0.85, max_tokens=700)
    except Exception as e:
        logger.exception("Ошибка ИИ (ask_ai_question): %s", e)
        return None


# ============================================================
# 5. ИТОГ ДНЯ
# ============================================================
def evening_messages(context: dict) -> dict:
    """«Тёплый вечер с бокалом»: живое напутствие и пара коротких касаний."""
    name = (context.get("name") or "").strip() or "друг"
    cal = context.get("calories") or 0
    norm = context.get("support_norm") or 0
    hour = context.get("hour") or 19
    drinks = context.get("drinks") or ""

    prompt = f"""Ты — «Добрый кот», тёплый помощник по питанию. Человек нажал «Тёплый вечер с бокалом»:
он собирается провести вечер с алкоголем и не хочет ни считать каждый глоток, ни слушать мораль.

Контекст: имя — {name}; съедено сегодня примерно {cal} ккал; норма поддержания около {norm} ккал;
сейчас около {hour}:00; за вечер уже записано: {drinks or "пока ничего"}.

Напиши JSON строго такого вида:
{{"intro": "2-3 предложения", "touches": ["одно предложение", "одно предложение"]}}

Требования:
- intro: тепло и по-человечески, без «нельзя», «плохо», «должен», без подсчётов вслух и без нотаций.
  Опирайся на контекст: если съедено мало — скажи, что вечер не испортит день; если много — спокойно,
  что завтра обычный день. Одно мягкое напутствие: чередовать бокал с водой.
- touches: две разные короткие фразы на потом (например про воду, про темп, про утро). Без повторов intro.
- Обращайся по имени, если оно есть. Одна эмодзи в конце максимум. Без Markdown, без списков, без кавычек внутри текста."""

    try:
        result = _extract_json(_ask(prompt, json_mode=True))
        if not isinstance(result, dict):
            return None
        intro = str(result.get("intro") or "").strip()
        touches = [str(t).strip() for t in (result.get("touches") or []) if str(t).strip()]
        if not intro:
            return None
        return {"intro": intro[:900], "touches": touches[:2]}
    except Exception as e:
        logger.exception("Ошибка ИИ (evening_messages): %s", e)
        return None


def generate_day_summary(user, summary, liquid_total, partial: bool = False):
    week = user.get('week', 1)
    cal = int(summary['calories']) if summary else 0
    prot = summary['protein'] if summary else 0
    fat = summary['fat'] if summary else 0
    carb = summary['carbs'] if summary else 0
    sugar = summary['sugar'] if summary else 0
    bad_fat = summary['bad_fat'] if summary else 0
    salt = summary['salt'] if summary and 'salt' in summary else 0

    partial_block = ""
    if partial:
        partial_block = (
            "11. ВАЖНО: сегодня записано меньше 35% дневной нормы. Это «день в бегах». "
            "НЕ оценивай БЖУ и сахар как итог дня, не хвали за «ноль сахара», не делай выводов о питании. "
            "Скажи мягко: записано мало, день был busy, это нормально; предложи вечером дополнить записи. 3-4 строки."
        )

    prompt = f"""Ты — Добрый Кот, помощник по питанию GOODKAT AI. Твоя задача — подвести итог дня пользователя мягко, тепло и поддерживающе.

ФАКТЫ ЗА ДЕНЬ:
- Калории: {cal} ккал
- Белок: {prot} г
- Жиры: {fat} г, Углеводы: {carb} г
- Добавленный сахар: {sugar} г
- Вредные жиры: {bad_fat} г
- Соль: {salt} г
- Жидкость: {liquid_total} мл
- Это неделя: {week}

ПРАВИЛА:
1. Начни с тёплого захода.
2. Похвали за то, что человек записывал.
3. Отметь, что получилось (1–2 пункта).
4. Дай ОДНУ мягкую подсказку на завтра.
5. Не стыди за превышения.
6. Запрещены слова: «должен», «надо», «обязан», «строго», «плохо», «нельзя».
7. Объём — 4–6 коротких строк.
8. В конце — поддержка.
9. Разметка: только теги <b> и <i>. Никакого Markdown (** и #).
10. НЕ здоровайся («привет», «доброе утро», «добрый вечер») — это итог дня, а не начало разговора.
{partial_block}

Отвечай по-русски, без JSON, просто текст."""

    try:
        return _ask(prompt, temperature=0.7, max_tokens=500)
    except Exception as e:
        logger.exception("Ошибка ИИ (generate_day_summary): %s", e)
        return None


# ============================================================
# 6. СЦЕНАРИЙ «НЕТ ВИНЫ» (Психологическая поддержка)
# ============================================================
def generate_no_guilt_message(calories: int, norm: int, dishes: list) -> str:
    dishes_str = ", ".join(dishes) if dishes else "разная еда"

    prompt = f"""Ты — Добрый Кот, заботливый помощник по питанию GOODKAT AI.
Человек сегодня съел {calories} ккал, а его норма поддержки — {norm} ккал. У него перебор.
Что он ел: {dishes_str}.

Твоя задача — написать сообщение (4-6 строк), которое пройдет по 3 шагам:
1. Легализация: Признай, что день был плотным, и это абсолютно нормально. Никакого стыда, паники или осуждения. Еда — это не ошибка.
2. Объяснение: Мягко напомни, что вес на следующий день может показаться больше — но это вода и объем еды (чтобы набрать 1 кг жира, нужно 7700 лишних ккал). Это не жир, и это уйдет.
3. Поддержка: Просто скажи, что ты рядом и это не катастрофа.

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:
- Давать любые советы (про спорт, прогулки, воду, голодание, разгрузочные дни).
- Использовать слова: «должен», «надо», «обязан», «строго», «плохо», «нельзя», «сорвался».
- Читать морали.
- Использовать Markdown. Разметка: только теги <b> и <i>.

Тон: мягкие лапы, тепло, забота, как добрый друг. Пиши по-русски, без JSON, просто текст."""

    try:
        return _ask(prompt, temperature=0.7, max_tokens=500)
    except Exception as e:
        logger.exception("Ошибка ИИ (generate_no_guilt_message): %s", e)
        return (
            "Вижу, сегодня был плотный день. Это нормально. 💚\n\n"
            "Вес завтра может показаться больше, но это вода и объем еды. Это не жир и скоро уйдет.\n\n"
            "Я рядом. Всё хорошо, завтра будет новый день. 🐾"
        )


# ============================================================
# 7. ЗАЙТИ КРАСИВО: ПЕРВАЯ НЕДЕЛЯ (полегче / поплотнее)
# ============================================================
def analyze_menu_first_week(menu_text: str) -> dict:
    prompt = f"""Ты — Добрый Кот, заботливый помощник по питанию. Человек прислал меню заведения (текст или описание фото). У него сейчас первая неделя — неделя привычек, без подсчёта калорий и норм.
Текст меню: "{menu_text}"

Твоя задача — разобрать меню и разделить блюда на две группы:
1. "lighter" — блюда, которые субъективно полегче (салаты, куриная грудка, овощи, лёгкие супы, гамбургер с салатом).
2. "denser" — блюда поплотнее (бургеры с картошкой, картофель фри, жирные соусы, десерты).

ПРАВИЛА:
- Не считай калории и не упоминай цифры.
- Бери блюда ТОЛЬКО из этого меню.
- В каждой группе — от 2 до 5 блюд.
- Если в тексте нет меню (набор букв, бред) — верни {{"is_menu": false}}.

Отвечай СТРОГО в формате JSON:
{{
  "is_menu": true,
  "lighter": ["блюдо 1", "блюдо 2"],
  "denser": ["блюдо 1", "блюдо 2"]
}}
Отвечай только JSON."""

    try:
        content = _ask(prompt, temperature=0.2, json_mode=True)
        result = _extract_json(content)
        return result if isinstance(result, dict) else {"is_menu": False}
    except Exception as e:
        logger.exception("Ошибка ИИ (analyze_menu_first_week): %s", e)
        return {"is_menu": False, "error": True}


# ============================================================
# 8. ЗАЙТИ КРАСИВО: ВТОРАЯ НЕДЕЛЯ (светофор по остатку)
# ============================================================
def analyze_menu_and_build_traffic_light(
    menu_text: str,
    remaining_loss: int,
    remaining_support: int,
    day_cal: int = 0,
    loss_high: int = 0,
    support_high: int = 0,
) -> dict:
    prompt = f"""Ты — Добрый Кот, заботливый помощник по питанию. Человек прислал меню заведения (текст или описание фото).
Текст меню: "{menu_text}"

Сегодня человек уже съел: {day_cal} ккал.
Его норма похудения (верхняя граница): {loss_high} ккал.
Его норма поддержания (верхняя граница): {support_high} ккал.

Остаток на сегодня:
- До нормы похудения осталось: {remaining_loss} ккал.
- До нормы поддержания осталось: {remaining_support} ккал.

Твоя задача — подобрать ТРИ варианта ИЗ ЭТОГО МЕНЮ (только реальные блюда/напитки из меню, не выдумывай):

1. "green" — вариант, который ВПИСЫВАЕТСЯ в остаток похудения ({remaining_loss} ккал). Суммарная калорийность НЕ БОЛЬШЕ {remaining_loss} ккал.
2. "yellow" — вариант, который ВПИСЫВАЕТСЯ в остаток поддержания ({remaining_support} ккал). Суммарная калорийность НЕ БОЛЬШЕ {remaining_support} ккал.
3. "red" — ОДНА самая калорийная позиция из меню (допустимо «блюдо + напиток», но не больше двух позиций), калорийность ВЫШЕ {remaining_support} ккал. Если даже самая калорийная позиция меню не дотягивает до {remaining_support} ккал — верни null, не выдумывай.

ВАЖНО:
- Состав варианта: салат и/или суп и/или основное блюдо и/или напиток и/или десерт. Ничего лишнего.
- В одном варианте НЕ БОЛЬШЕ ОДНОГО напитка: два кофе, кофе + сок, чай + кола — ошибка. Выбери один напиток.
- Не больше одного салата, одного супа, одного основного блюда, одного гарнира и одного десерта в варианте.
- Не сваливай всё меню в один ответ: больше четырёх позиций — ошибка.
- У каждого варианта ОБЯЗАТЕЛЬНО должно быть поле "dish" с названием выбранных позиций через " + ".
- У каждого варианта ОБЯЗАТЕЛЬНО должно быть поле "items": список позиций варианта, у каждой "name" (название из меню), "kind" (салат / суп / основное / гарнир / напиток / десерт) и "calories" (калории именно этой позиции). Сумма "calories" в items должна равняться общему "calories" варианта.
- Ориентиры калорийности напитков (не завышай): эспрессо 30 мл ~3 ккал, американо 200 мл ~5, капучино 200 мл ~80, флэт уайт 200 мл ~120, латте 300 мл ~150, раф 300 мл ~250, какао 300 мл ~200, бабл ти 400 мл ~300, свежевыжатый сок 250 мл ~110.
- Если остаток похудения = 0 — предложи зелёный вариант с минимальной калорийностью.
- Калорийность указывай честно и примерно.
- Бери ТОЛЬКО блюда из меню.
- Если в тексте нет меню — верни {{"is_menu": false}}.

Отвечай СТРОГО в формате JSON:
{{
  "is_menu": true,
  "green": {{"dish": "Капучино + Круасан", "calories": 460, "items": [{{"name": "Капучино", "calories": 140}}, {{"name": "Круасан", "calories": 320}}], "protein": 8, "fat": 25, "carbs": 45, "weight": 250}},
  "yellow": {{"dish": "Салат Цезарь с курицей + Овощи тушёные с говядиной", "calories": 780, "items": [{{"name": "Салат Цезарь с курицей", "calories": 340}}, {{"name": "Овощи тушёные с говядиной", "calories": 440}}], "protein": 40, "fat": 30, "carbs": 55, "weight": 500}},
  "red": {{"dish": "Стейк из говядины + Картофель фри", "calories": 1000, "items": [{{"name": "Стейк из говядины", "calories": 700}}, {{"name": "Картофель фри", "calories": 300}}], "protein": 55, "fat": 60, "carbs": 40, "weight": 500}}
}}
Если какого-то варианта нет — поставь null. Отвечай только JSON."""

    try:
        content = _ask(prompt, temperature=0.2, json_mode=True)
        result = _extract_json(content)
        return result if isinstance(result, dict) else {"is_menu": False}
    except Exception as e:
        logger.exception("Ошибка ИИ (analyze_menu): %s", e)
        return {"is_menu": False, "error": True}
