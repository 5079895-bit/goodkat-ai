"""Проверки колы и сладких напитков."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b7.db")
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
    async def edit_reply_markup(self, reply_markup=None): self.sent.append("[кнопки]"); return self


async def main():
    database.init_db()
    uid = 818
    database.create_user(uid); database.set_step(uid, 10); database.save_answer(uid, "week", 2)
    database.save_answer(uid, "gender", "М"); database.save_answer(uid, "height", 180)
    database.save_answer(uid, "weight", 90); database.save_answer(uid, "age", 40)
    database.save_answer(uid, "lifestyle", "умеренный")

    captured = {}
    def fake(dish, details):
        captured["details"] = details
        zero = "зеро" in details
        cal = 1 if zero else 139
        return {"dish": dish, "weight": 330, "calories": cal, "protein": 0, "fat": 0,
                "carbs": 0 if zero else 35, "sugar": 0 if zero else 35, "bad_fat": 0,
                "salt": 0, "is_liquid": True, "ml": 330}
    bot.ai.calculate_nutrition = fake
    bot.ai.split_components = lambda t: [t]
    bot.ai.get_questions_for_ai = lambda t: {"dish": t, "questions": []}

    # 1. кола — вопрос «обычная или Zero»
    m = M(uid, "кола 330")
    await bot._handle_message_locked(m)
    check("на колу спрашивает обычная/Zero",
          "Обычная или Zero" in m.sent[-1], m.sent[-1][:80])
    check("в вопросе подсказка про zero", "zero" in m.sent[-1].lower(), m.sent[-1][:90])

    # 2. обычная — текстом
    m_ans = M(uid, "обычная")
    await bot._handle_message_locked(m_ans)
    check("«Обычная» уходит в расчёт с сахаром", "обычная" in captured.get("details", ""), captured.get("details"))
    conn = database._connect()
    row = dict(conn.execute("SELECT dish, calories FROM food_log WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone())
    conn.close()
    check("обычная кола — 139 ккал", row["calories"] == 139, row)

    # 3. zero
    m2 = M(uid, "кола 330")
    await bot._handle_message_locked(m2)
    m_zero = M(uid, "zero")
    await bot._handle_message_locked(m_zero)
    conn = database._connect()
    row2 = dict(conn.execute("SELECT dish, calories FROM food_log WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone())
    conn.close()
    check("Zero — 1 ккал", row2["calories"] == 1, row2)

    # 4. если Zero уже сказано — не спрашиваем
    bot._pending_clarification.pop(uid, None)
    m3 = M(uid, "кола зеро 330")
    await bot._handle_message_locked(m3)
    check("«кола зеро» без вопроса", "Обычная или Zero" not in " ".join(m3.sent), m3.sent[-1][:80])

    # 5. фанта тоже спрашивает
    bot._pending_clarification.pop(uid, None)
    m4 = M(uid, "фанта 330")
    await bot._handle_message_locked(m4)
    check("фанта тоже спрашивает", "Обычная или Zero" in m4.sent[-1], m4.sent[-1][:70])

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
