"""Вино: спрашиваем какое — сухое, полусухое, сладкое."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b18.db")
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
    # 1. определение вина
    for t in ("вино 150", "вина 150", "вином 150", "шампанское 200", "просекко 150"):
        check(f"вино распознано: {t}", ai.needs_wine_question(t, []) is True)
    check("«винегрет» — не вино", ai.needs_wine_question("винегрет 200", []) is False)
    check("«сухое вино 150» — тип назван", ai.needs_wine_question("сухое вино 150", []) is False)
    check("«полусладкое 150» — тип назван", ai.needs_wine_question("полусладкое вино 150", []) is False)

    # 2. вопрос попадает в список и не превышает трёх
    q = ai.ensure_questions("вино 150", [])
    check("вино: спросили тип", q and "сухое" in q[0].lower(), q)
    q2 = ai.ensure_questions("вино", [])
    check("вино без объёма: сначала мл, потом тип",
          len(q2) == 2 and "мл" in q2[0].lower() and "сухое" in q2[1].lower(), q2)

    # 3. быстрый расчёт не проскакивает мимо вопроса
    check("«вино 150» не считается сразу", bot._quick_details("вино 150") is None)
    check("«вино 150 сухое» — вопросов нет", ai.ensure_questions("вино 150 сухое", []) == [])

    # 4. живой сценарий на заглушке
    database.init_db()
    bot.ai.calculate_nutrition = lambda d, det: {
        "dish": "Вино сухое красное", "weight": 150, "calories": 110, "protein": 0.1, "fat": 0,
        "carbs": 0.5, "sugar": 0.5, "bad_fat": 0, "salt": 0, "is_liquid": True, "ml": 150}

    uid = 8800
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid, k, v)

    m = M(uid, "вино 150")
    await bot._handle_message_locked(m)
    check("вино 150: спросил тип, а не записал", "сухое" in m.sent[-1].lower(), m.sent[-1][:80])

    m2 = M(uid, "сухое красное")
    await bot._handle_message_locked(m2)
    reply = m2.sent[-1]
    check("после ответа — записал 150 мл", "150 мл" in reply, reply.split("\n")[0][:70])
    check("калории посчитаны", "110" in reply, reply.split("\n")[1][:30] if "\n" in reply else "")

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
