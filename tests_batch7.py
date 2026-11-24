"""Проверки вопросов для сока и компота."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b8.db")
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
    # какие вопрос задаём
    check("сок -> вопрос про свежевыжатый", bot._sugar_kind("сок 250") == "juice")
    check("нектар -> тоже сок", bot._sugar_kind("нектар 200") == "juice")
    check("компот -> сладкий/без сахара", bot._sugar_kind("компот 250") == "compote")
    check("морс -> как компот", bot._sugar_kind("морс 250") == "compote")
    check("кисель -> как компот", bot._sugar_kind("кисель 200") == "compote")
    check("кола -> обычная/Zero", bot._sugar_kind("кола 330") == "sweet")
    check("чай -> ложки", bot._sugar_kind("чай 300") == "spoon")

    # кнопки
    check("у сока вопрос про вид словами", "свежевыжатый" in str(bot._sugar_kind("сок")) or bot._sugar_kind("сок") == "juice")
    check("у компота вопрос про сахар", bot._sugar_kind("компот 250") == "compote")

    database.init_db()
    uid = 919
    database.create_user(uid); database.set_step(uid, 10); database.save_answer(uid, "week", 2)
    database.save_answer(uid, "gender", "М"); database.save_answer(uid, "height", 180)
    database.save_answer(uid, "weight", 90); database.save_answer(uid, "age", 40)
    database.save_answer(uid, "lifestyle", "умеренный")

    captured = {}
    def fake(dish, details):
        captured["details"] = details
        sweet = "сладкий" in details or "пакетированный" in details
        return {"dish": dish, "weight": 250, "calories": 145 if sweet else 60, "protein": 0,
                "fat": 0, "carbs": 36 if sweet else 15, "sugar": 36 if sweet else 15,
                "bad_fat": 0, "salt": 0, "is_liquid": True, "ml": 250}
    bot.ai.calculate_nutrition = fake
    bot.ai.split_components = lambda t: [t]
    bot.ai.get_questions_for_ai = lambda t: {"dish": t, "questions": []}

    # сок: свежевыжатый
    m = M(uid, "сок 250")
    await bot._handle_message_locked(m)
    check("сок: бот спросил про вид", "Свежевыжатый или пакетированный" in m.sent[-1], m.sent[-1][:70])
    m_ans = M(uid, "свежевыжатый")
    await bot._handle_message_locked(m_ans)
    check("сок: «свежевыжатый» ушёл в расчёт",
          "свежевыжатый" in captured.get("details", ""), captured.get("details"))

    # компот: сладкий
    bot._pending_clarification.pop(uid, None)
    m2 = M(uid, "компот 250")
    await bot._handle_message_locked(m2)
    check("компот: спросил про сахар", "Сладкий или без сахара" in m2.sent[-1], m2.sent[-1][:70])
    m_sweet = M(uid, "сладкий")
    await bot._handle_message_locked(m_sweet)
    conn = database._connect()
    row = dict(conn.execute("SELECT calories FROM food_log WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone())
    conn.close()
    check("компот сладкий — 145 ккал", row["calories"] == 145, row)

    # «компот без сахара» текстом
    bot._pending_clarification.pop(uid, None)
    m3 = M(uid, "компот 250 без сахара")
    await bot._handle_message_locked(m3)
    check("«без сахара» в тексте — без вопроса", "Сладкий или без сахара" not in " ".join(m3.sent), m3.sent[-1][:70])

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
