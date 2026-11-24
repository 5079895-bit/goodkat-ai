"""Объём доспрашивается отдельно; «по-французски» — блюдо, а не свинина."""
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
    # 1. формулировка вопроса: мл для жидкости, граммы для густого
    q_liquid = ai.ensure_questions("ряженка", [])
    q_solid = ai.ensure_questions("творог", [])
    check("ряженка — спрашиваем миллилитры", q_liquid and "миллилитр" in q_liquid[0].lower(), q_liquid)
    check("творог — спрашиваем граммы", q_solid and "грамм" in q_solid[0].lower(), q_solid)

    # 2. «по-французски» — рецепт, а не кусок мяса
    r = ai.ensure_questions("свинина по-французски 200", [])
    check("по-французски: один вопрос", len(r) == 1, r)
    check("по-французски: спросили майонез/сыр", r and ("майонез" in r[0].lower() or "сыр" in r[0].lower()), r)
    check("по-французски: не спрашиваем «сырое/готовое»", not any("варёное" in x.lower() for x in r), r)
    check("быстрый расчёт не считает как свинину", bot._quick_details("свинина по-французски 200") is None)
    check("«свинина 200» — не рецепт", ai.needs_recipe_question("свинина 200", []) is False)
    check("«мясо по-французски» — порция + майонез",
          len(ai.ensure_questions("мясо по-французски", [])) == 2)

    # 3. ответ только жирностью -> объём доспрашиваем
    database.init_db()
    bot.ai.calculate_nutrition = lambda d, det: {
        "dish": "Ряженка 4%", "weight": 250, "calories": 168, "protein": 7.3, "fat": 10,
        "carbs": 10.3, "sugar": 0, "bad_fat": 0, "salt": 0, "is_liquid": True, "ml": 250}

    uid = 6600
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid, k, v)

    m = M(uid, "ряженка")
    await bot._handle_message_locked(m)
    check("ряженка: первый вопрос про объём и жирность",
          "миллилитр" in m.sent[-1].lower() and "жирност" in m.sent[-1].lower(), m.sent[-1][:80])

    m2 = M(uid, "4")
    await bot._handle_message_locked(m2)
    check("ответил только жирностью — спросили объём", "мл" in m2.sent[-1].lower(), m2.sent[-1][:80])

    m3 = M(uid, "250")
    await bot._handle_message_locked(m3)
    check("после объёма — записал 250 мл", "250 мл" in m3.sent[-1], m3.sent[-1].split("\n")[0][:80])

    # 4. если объём назван сразу — про объём не спрашиваем
    uid2 = 6601
    database.create_user(uid2); database.set_step(uid2, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid2, k, v)

    m4 = M(uid2, "ряженка 250")
    await bot._handle_message_locked(m4)
    check("ряженка 250: только жирность", "миллилитр" not in m4.sent[-1].lower()
          and "жирност" in m4.sent[-1].lower(), m4.sent[-1][:80])

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
