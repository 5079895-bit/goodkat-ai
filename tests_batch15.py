"""Молочная жирность и «рибай» вместо прощания."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b16.db")
import bot, ai

ok = []
def check(name, cond, detail=""):
    ok.append((name, cond))
    print(("PASS  " if cond else "FAIL  ") + name + ((" | " + str(detail)) if detail else ""))


class M:
    def __init__(self, uid, text=None):
        self.from_user = type("U", (), {"id": uid})()
        self.text = text; self.photo = None; self.caption = None
        self.chat = type("C", (), {"id": uid})(); self.message_id = 1
        self.sent = []
    async def answer(self, text, **kw): self.sent.append(text); return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


async def main():
    # 1. жирность спрашиваем у всего молочного
    for dish in ("кефир 250", "молоко 200", "творог 150", "сметана 20", "йогурт 125",
                 "ряженка 250", "айран 300", "простокваша 200", "сыр 30", "сливки 50"):
        check(f"жирность спрашиваем: {dish}", ai.needs_fat_question(dish, []) is True)

    check("жирность названа — не спрашиваем", ai.needs_fat_question("кефир 2,5% 250", []) is False)
    check("«обезжиренный» — не спрашиваем", ai.needs_fat_question("творог обезжиренный 150", []) is False)
    check("борщ — не молочное", ai.needs_fat_question("борщ 300", []) is False)

    q = ai.ensure_questions("молоко 200", [])
    check("вопрос про жирность попал в список", any("жирност" in x.lower() for x in q), q)

    # 2. быстрый расчёт не проскакивает жирность
    check("«кефир 250» не считается сразу", bot._quick_details("кефир 250") is None)
    check("«молоко 200» не считается сразу", bot._quick_details("молоко 200") is None)

    # 3. «рибай» — это не «бай»
    check("«рибай стейк» не прощание", bot._service_reply("рибай стейк") is None)
    check("«пока» — прощание", bot._service_reply("пока") == "До связи! Не забудь записать. 👋")
    check("«спасибо» — благодарность", "Пожалуйста" in bot._service_reply("спасибо"))
    check("«привет» — приветствие", "Привет" in bot._service_reply("привет"))

    # 4. живые сценарии
    database.init_db()
    bot.ai.split_components = lambda t: [t]
    bot.ai.get_questions_for_ai = lambda t: {"dish": t, "questions": []}
    bot.ai.calculate_nutrition = lambda d, det: {
        "dish": "Молоко 3,2%", "weight": 200, "calories": 118, "protein": 5.8, "fat": 6.4,
        "carbs": 9.4, "sugar": 0, "bad_fat": 0, "salt": 0, "is_liquid": True, "ml": 200}

    for i, text in enumerate(("молоко 200", "рибай стейк 250")):
        uid = 9600 + i
        database.create_user(uid); database.set_step(uid, 10)
        for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                     ("age", 45), ("lifestyle", "сидячий")]:
            database.save_answer(uid, k, v)

        m = M(uid, text)
        await bot._handle_message_locked(m)
        first = m.sent[-1]
        if text.startswith("молоко"):
            check("молоко: спросил жирность", "жирност" in first.lower(), first[:70])
            m2 = M(uid, "3,2")
            await bot._handle_message_locked(m2)
            check("молоко: записал с жирностью", "3,2%" in m2.sent[-1], m2.sent[-1][:70])
        else:
            check("рибай: не попрощался", "До связи" not in first, first[:70])
            check("рибай: спросил по делу", "?" in first and "вес" in first.lower() or "приготов" in first.lower(),
                  first[:70])

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
