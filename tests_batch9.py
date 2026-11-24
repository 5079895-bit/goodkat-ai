"""Проверки: вопросы про состав блюд и объём напитков."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b10.db")
import bot

ok = []
def check(name, cond, detail=""):
    ok.append((name, cond))
    print(("PASS  " if cond else "FAIL  ") + name + ((" | " + str(detail)) if detail else ""))


class M:
    def __init__(self, uid, text=None):
        self.from_user = type("U", (), {"id": uid})()
        self.text = text; self.photo = None; self.caption = None
        self.chat = type("C", (), {"id": uid})(); self.message_id = 1
        self.html_text = ""; self.sent = []; self.markup = None
    async def answer(self, text, **kw):
        self.sent.append(text)
        if kw.get("reply_markup") is not None: self.markup = kw["reply_markup"]
        return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


async def main():
    # спорные блюда не считаем «сразу по количеству»
    check("котлета 100 не уходит в быстрый расчёт", bot._quick_details("котлета 100") is None)
    check("плов 300 не уходит в быстрый расчёт", bot._quick_details("плов 300") is None)
    check("борщ 300 г по-прежнему сразу", bot._quick_details("борщ 300 г") == "300 г")
    check("гречка 200 сразу", bot._quick_details("гречка 200") == "200 г")

    # объём в вопросе
    check("объём в «кола 330» распознан", bot._has_volume("кола 330") is True)
    check("«кола» без объёма", bot._has_volume("кола") is False)
    check("«стакан сока» считается объёмом", bot._has_volume("стакан сока") is True)

    database.init_db()
    uid = 111
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 180), ("weight", 90),
                 ("age", 40), ("lifestyle", "умеренный")]:
        database.save_answer(uid, k, v)

    captured = {}
    def fake(dish, details):
        captured["dish"], captured["details"] = dish, details
        return {"dish": dish, "weight": 300, "calories": 200, "protein": 10, "fat": 9,
                "carbs": 15, "sugar": 0, "bad_fat": 0, "salt": 0, "is_liquid": False, "ml": None}
    bot.ai.calculate_nutrition = fake
    bot.ai.split_components = lambda t: [t]
    bot.ai.get_questions_for_ai = lambda t: {
        "dish": "котлета", "questions": ["Из какого мяса и как приготовлена?"]}

    # котлета: спрашивает состав, ответ уходит в расчёт
    m = M(uid, "котлета 100")
    await bot._handle_message_locked(m)
    check("на котлету бот спрашивает состав",
          any("Из какого мяса" in t for t in m.sent), m.sent[-1][:70])
    m2 = M(uid, "свинина, жареная")
    await bot._handle_message_locked(m2)
    check("ответ про мясо попал в расчёт", "свинина" in captured.get("details", ""), captured.get("details"))

    # напиток без объёма: сначала объём, потом вид — по одному вопросу
    bot.ai.get_questions_for_ai = lambda t: {"dish": t, "questions": []}
    bot._pending_clarification.pop(uid, None)
    m3 = M(uid, "кола")
    await bot._handle_message_locked(m3)
    check("на «кола» сначала спрашивает объём", "Сколько миллилитров" in m3.sent[-1], m3.sent[-1][:90])

    m4 = M(uid, "0,5 л")
    await bot._handle_message_locked(m4)
    check("после объёма спрашивает вид", "Обычная или Zero" in m4.sent[-1], m4.sent[-1][:90])

    m5 = M(uid, "обычная")
    await bot._handle_message_locked(m5)
    check("объём из ответа не потерялся", "500 мл" in captured.get("details", ""), captured.get("details"))
    check("вид тоже сохранён", "обычная" in captured.get("details", ""), captured.get("details"))

    # если про объём сказали «не знаю» — стандарт, но с пометкой
    bot._pending_clarification.pop(uid, None)
    m6 = M(uid, "чай")
    await bot._handle_message_locked(m6)
    m7 = M(uid, "не знаю")
    await bot._handle_message_locked(m7)
    m8 = M(uid, "2 ложки")
    await bot._handle_message_locked(m8)
    check("без объёма — пометка про стандартную порцию",
          "стандартную порцию" in captured.get("details", ""), captured.get("details"))
    check("сахар при этом посчитан", "сахар 2" in captured.get("details", ""), captured.get("details"))

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
