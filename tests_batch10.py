"""Проверки кефира/молока: жирность не путается с объёмом."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b11.db")
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
        self.sent.append(text); return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


async def main():
    # жирность не считается объёмом
    check("«кефир 2,5» — не 2 мл", bot._quick_details("кефир 2,5") is None, bot._quick_details("кефир 2,5"))
    check("«кефир 1% 300» — не 1 мл", bot._quick_details("кефир 1% 300") is None)
    check("«кефир 2,5% 250 мл»", bot._quick_details("кефир 2,5% 250 мл") is None)

    # нормальные объёмы по-прежнему работают
    check("«кефир 250» не считаем без жирности", bot._quick_details("кефир 250") is None)
    check("«кефир 2,5% 250» — жирность не спрашиваем",
          bot.ai.needs_fat_question("кефир 2,5% 250", []) is False)
    check("«молоко 200» не считаем без жирности", bot._quick_details("молоко 200") is None)
    check("«кола 0,5» -> пол-литра", bot._quick_details("кола 0,5") == "500 мл")
    check("«вино 0,5 л» не считаем без типа", bot._quick_details("вино 0,5 л") is None)
    check("«пиво 1,5 л» -> 1500 мл", bot._quick_details("пиво 1,5 л") == "1500 мл")

    database.init_db()
    uid = 202
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 180), ("weight", 90),
                 ("age", 40), ("lifestyle", "умеренный")]:
        database.save_answer(uid, k, v)

    captured = {}
    def fake(dish, details):
        captured["details"] = details
        return {"dish": "Кефир 2,5%", "weight": 250, "calories": 133, "protein": 7.3,
                "fat": 6.3, "carbs": 10, "sugar": 0, "bad_fat": 0, "salt": 0,
                "is_liquid": True, "ml": 250}
    bot.ai.calculate_nutrition = fake
    bot.ai.split_components = lambda t: [t]
    bot.ai.get_questions_for_ai = lambda t: {"dish": "Кефир 2,5%", "questions": []}

    m = M(uid, "кефир 2,5")
    await bot._handle_message_locked(m)
    check("«кефир 2,5» не превращается в 2 мл", "2 мл" not in m.sent[-1], m.sent[-1][:70])
    check("спрашивает объём, а не угадывает", "Сколько примерно мл" in m.sent[-1], m.sent[-1][:70])

    m2 = M(uid, "250")
    await bot._handle_message_locked(m2)
    reply = m2.sent[-1]
    check("жирность уже названа — после объёма сразу запись", "записал" in reply.lower(), reply[:70])
    check("единицы для жидкости — мл", "(250 мл)" in reply, reply.split("\n")[0])
    check("объём 250 мл попал в расчёт", "250" in captured.get("details", ""), captured.get("details"))
    check("объём не подставлен как 2 мл в расчёт", "2 мл" not in captured.get("details", ""), captured.get("details"))

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
