"""Прогон бота GOODKAT без Telegram: проверяем логику, БД и обработчики."""
import os, sys, asyncio, tempfile, threading, re, json

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-not-real")

import database

TMP = tempfile.mkdtemp()
database.DB_PATH = os.path.join(TMP, "test.db")

import bot  # noqa: E402
import ai   # noqa: E402

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS  " if ok else "FAIL  ") + name + ((" | " + str(detail)) if detail else ""))


class FakeMessage:
    def __init__(self, uid, text=None, photo=None):
        self.from_user = type("U", (), {"id": uid})()
        self.text = text
        self.caption = None
        self.photo = photo
        self.chat = type("C", (), {"id": uid})()
        self.message_id = 1
        self.html_text = ""
        self.sent = []

    async def answer(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return type("M", (), {"chat": self.chat, "message_id": 2})()

    async def edit_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))
        return self


def stub_ai(cal=250, dish_override=None, questions=None):
    ai.get_questions_for_ai = lambda t: {"dish": dish_override or t, "questions": questions or []}
    ai.calculate_nutrition = lambda d, det: {
        "dish": dish_override or d, "weight": 300, "calories": cal, "protein": 10,
        "fat": 8, "carbs": 30, "sugar": 0, "bad_fat": 0, "salt": 1,
        "is_liquid": False, "ml": None,
    }
    ai.split_components = lambda t: [t]
    ai.generate_day_summary = lambda *a, **k: "Тёплый итог дня."
    ai.generate_no_guilt_message = lambda *a, **k: "Всё нормально."


def tg_html_problem(text):
    """Грубая проверка по правилам telegram HTML parse_mode."""
    if re.search(r"&(?!(amp|lt|gt|quot|#\d+);)", text):
        return "неэкранированный &"
    for m in re.finditer(r"<(?!\/?(b|i|u|s|code|pre|a|em|strong|tg-spoiler)[\s>])", text):
        return f"подозрительный '<' в позиции {m.start()}"
    return None


async def run_dialog():
    uid = 501
    # ---------- 1. Вход по коду ----------
    database.init_db()
    m = FakeMessage(uid, "1234")
    await bot._handle_message_locked(m)
    u = database.get_user(uid)
    check("регистрация по коду 1234 (значение по умолчанию)", u is not None and u["survey_step"] == 1)

    m = FakeMessage(uid, "Аня"); await bot._handle_message_locked(m)
    m = FakeMessage(uid, "30");  await bot._handle_message_locked(m)
    m = FakeMessage(uid, bot.BTN_AGREE); await bot._handle_message_locked(m)
    m = FakeMessage(uid, "UTC+3 (Москва, Питер)"); await bot._handle_message_locked(m)
    m = FakeMessage(uid, "1");   await bot._handle_message_locked(m)
    u = database.get_user(uid)
    check("опрос: имя/возраст/пояс/выбор пути пройдены", u["survey_step"] == 10 and u["utc_offset"] == 3, f"step={u['survey_step']}")

    # ---------- 2. Запись еды ----------
    stub_ai(cal=250)
    m = FakeMessage(uid, "борщ 300")
    await bot._handle_message_locked(m)
    today = database._get_user_date(uid, 3)
    summary = database.get_day_summary(uid, today)
    check("еда записалась в БД", summary is not None and summary["calories"] == 250, summary)

    # ---------- 3. Итог дня: только вечером ----------
    from datetime import datetime, timezone
    utc_hour = datetime.now(timezone.utc).hour
    database.save_answer(uid, "utc_offset", (12 - utc_hour) % 24)   # у человека полдень
    m = FakeMessage(uid, "итог")
    await bot._handle_message_locked(m)
    check("днём итог не показывается",
          not any("Твои итоги" in t for t, _ in m.sent), m.sent[-1][0][:60] if m.sent else "")

    database.save_answer(uid, "utc_offset", (21 - utc_hour) % 24)   # у человека 21:00
    bot.ai.generate_day_summary = lambda *a, **k: "ИТОГ-ТЕСТ"
    m = FakeMessage(uid, "итог")
    await bot._handle_message_locked(m)
    check("вечером итог показывается",
          any("Твои итоги" in t or "ИТОГ-ТЕСТ" in t for t, _ in m.sent), m.sent[-1][0][:60] if m.sent else "")

    # ---------- 4. Исправление последней записи ----------
    stub_ai(cal=400, dish_override="борщ с мясом")
    bot._pending_clarification[uid] = {"is_fix": True}
    m = FakeMessage(uid, "борщ 400")
    await bot._handle_message_locked(m)
    summary = database.get_day_summary(uid, today)
    check("исправление перезаписало, а не добавило", summary["calories"] == 400, summary["calories"])

    # ---------- 5. Удаление ----------
    cb = type("CB", (), {})()
    cb.from_user = type("U", (), {"id": uid})()
    cb.message = FakeMessage(uid)
    cb.message.html_text = "текст"
    cb.answer = lambda *a, **k: asyncio.sleep(0)
    await bot.cb_delete_last(cb)
    check("удаление убрало запись", database.get_day_summary(uid, today) is None)

    # ---------- 6. Цена ошибки ИИ: HTML ----------
    stub_ai()
    ai.ask_ai_question = lambda q: "Белки & жиры < 10 г, а <b>углеводы</b> важны."
    bot._help_mode.add(uid)
    m = FakeMessage(uid, "что такое белок")
    await bot._handle_message_locked(m)
    sent = m.sent[-1][0]
    prob = tg_html_problem(sent)
    check("ответ ИИ в режиме помощи не ломает HTML", prob is None, prob or "ok")

    # ---------- 7. Итог дня с ответом ИИ, содержащим & ----------
    bot._help_mode.clear(); bot._help_waiting_answer.clear()
    stub_ai(cal=250)
    ai.generate_day_summary = lambda *a, **k: "Ты молодец & так держать. <b>Завтра</b> легче."
    m = FakeMessage(uid, "борщ 300"); await bot._handle_message_locked(m)
    m = FakeMessage(uid, "итог"); await bot._handle_message_locked(m)
    prob = tg_html_problem(m.sent[-1][0])
    check("итог дня с ответом ИИ не ломает HTML", prob is None, prob or "ok")

    # ---------- 8. Меню: green без ключа dish ----------
    uid2 = 777
    database.create_user(uid2)
    database.set_step(uid2, 10)
    database.save_answer(uid2, "week", 2)
    database.save_answer(uid2, "gender", "Ж")
    database.save_answer(uid2, "height", 165)
    database.save_answer(uid2, "weight", 60)
    database.save_answer(uid2, "age", 30)
    database.save_answer(uid2, "lifestyle", "умеренный")
    ai.analyze_menu_and_build_traffic_light = lambda *a, **k: {"is_menu": True, "green": {"calories": 300}, "yellow": None, "red": None}
    bot._pending_menu_mode[uid2] = {"waiting": True}
    m = FakeMessage(uid2, "Салат Цезарь, Борщ, Паста")
    crashed = None
    try:
        await bot._handle_work(m, uid2, "Салат Цезарь, Борщ, Паста")
    except Exception as e:
        crashed = f"{type(e).__name__}: {e}"
    check("меню: ответ ИИ без поля dish не роняет бота", crashed is None, crashed or "ok")

    # ---------- 9. Помощь: новый вопрос вместо да/нет ----------
    bot._help_mode.add(uid)
    stub_ai()
    ai.ask_ai_question = lambda q: "Ответ на вопрос."
    m = FakeMessage(uid, "вопрос 1"); await bot._handle_message_locked(m)
    m = FakeMessage(uid, "а сколько в арбузе калорий?"); await bot._handle_message_locked(m)
    check("после ответа можно задать новый вопрос, а не только да/нет",
          "Напиши 'да' или 'нет'" not in m.sent[-1][0], m.sent[-1][0][:60])


async def run_units():
    # ---------- JSON ----------
    cases = [
        ('{"dish": "борщ", "questions": []}', True),
        ('Вот ответ:\n{"dish": "борщ", "questions": []}\nГотово', True),
        ('```json\n{"dish": "борщ", "questions": []}\n```', True),
        ('{"dish": "суп"} и ещё {"note": "x"}', True),
        ('Извини, не понял', False),
    ]
    for raw, expect in cases:
        got = ai._extract_json(raw)
        check(f"_extract_json: {raw[:34]!r}", (got is not None) == expect, got)

    # ---------- БД: строковые числа ----------
    database.init_db()
    uid = 900
    database.create_user(uid)
    database.add_food(uid, "2026-11-23", "борщ", "450 ккал", 10, 5, 30, 0, 0, 300)
    s = database.get_day_summary(uid, "2026-11-23")
    check("текстовые числа от ИИ не теряются в сумме", s["calories"] == 450, s)

    # ---------- БД: недельный фильтр и часовой пояс ----------
    uid = 901
    database.create_user(uid)
    utc_today = database.datetime.now(database.timezone.utc).strftime("%Y-%m-%d")
    # имитируем пользователя, у которого местная дата на день впереди UTC (после 21:00 МСК)
    base = database.datetime.strptime(database.local_today(3), "%Y-%m-%d")
    for k in (-2, -1, 0):
        database.add_food(uid, (base + database.timedelta(days=k)).strftime("%Y-%m-%d"), "еда", 100, 1, 1, 1, 0, 0, 100)
    got = database.get_unique_food_days_for_week(uid, 1)   # «последние 2 дня» по местному времени
    check("недельный фильтр считает по местной дате",
          got == 2, f"посчитал дней: {got}, ожидалось 2 (в базе 3 дня подряд)")

    # а вот как расходятся старый и новый расчёт в 21:30 по Москве
    moment = database.datetime(2026, 11, 23, 21, 30, tzinfo=database.timezone.utc)
    old_cut = (moment - database.timedelta(days=1)).date()
    new_cut = (moment + database.timedelta(hours=3) - database.timedelta(days=1)).date()
    check("в 21:30 МСК старый расчёт брал лишний день", old_cut != new_cut, f"UTC-граница {old_cut}, местная {new_cut}")

    # ---------- Нормы ----------
    user = {"gender": "Ж", "weight": 60.0, "height": 165, "age": 30, "lifestyle": "умеренный"}
    n = bot._calc_norms(user)
    ok = 1200 <= n["loss_low"] <= n["loss_high"] <= n["support_high"] <= 3000
    check("нормы выглядят здраво", ok, n)

    # ---------- Конкурентная запись ----------
    uid = 902
    database.create_user(uid)
    errors = []
    def worker(k):
        try:
            for i in range(15):
                database.add_food(uid, "2026-11-23", f"еда{k}-{i}", 100, 1, 1, 1, 0, 0, 100)
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
    ts = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    s = database.get_day_summary(uid, "2026-11-23")
    check("8 потоков пишут без ошибок 'database is locked'", not errors, errors[:2] or f"строк={s['calories']/100:.0f}")


async def main():
    print("=== ДИАЛОГ ===")
    await run_dialog()
    print("\n=== МОДУЛИ ===")
    await run_units()
    print("\n=== ИТОГ ===")
    bad = [n for n, ok, _ in results if not ok]
    print(f"проверок: {len(results)}, провалено: {len(bad)}")
    for n in bad:
        print("  ✗", n)

asyncio.run(main())
