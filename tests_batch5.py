"""Проверки уточнения по сахару."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b6.db")
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
    async def edit_reply_markup(self, reply_markup=None): self.sent.append("[кнопки убраны]"); return self


async def main():
    database.init_db()
    uid = 717
    database.create_user(uid); database.set_step(uid, 10); database.save_answer(uid, "week", 2)
    database.save_answer(uid, "gender", "М"); database.save_answer(uid, "height", 180)
    database.save_answer(uid, "weight", 90); database.save_answer(uid, "age", 40)
    database.save_answer(uid, "lifestyle", "умеренный")
    today = database._get_user_date(uid, 3)

    import re as _re
    captured = {}
    def fake_nutrition(dish, details):
        captured["dish"], captured["details"] = dish, details
        m = _re.search(r"сахар (\d+(?:\.\d+)?) (ч\.л\.|г)", details or "")
        if m:
            sugar = float(m.group(1)) * (6 if m.group(2) == "ч.л." else 1)
        else:
            sugar = 0
        return {"dish": dish, "weight": 300, "calories": 3 + sugar * 4, "protein": 0, "fat": 0,
                "carbs": sugar, "sugar": sugar, "bad_fat": 0, "salt": 0, "is_liquid": True, "ml": 300}
    bot.ai.calculate_nutrition = fake_nutrition
    bot.ai.split_components = lambda t: [t]
    bot.ai.get_questions_for_ai = lambda t: {"dish": t, "questions": []}

    # 1. чай с количеством -> вопрос про сахар
    m = M(uid, "чай 300")
    await bot._handle_message_locked(m)
    check("на «чай 300» бот спрашивает про сахар",
          any("сахар" in t.lower() for t in m.sent), m.sent[-1][:80])
    check("вопрос про сахар с подсказкой про ложки и граммы",
          "ложек" in m.sent[-1] and "граммов" in m.sent[-1], m.sent[-1][:90])
    check("в уточнении сохранён исходный текст с порцией",
          "300" in bot._pending_clarification[uid].get("original_text", ""),
          bot._pending_clarification[uid].get("original_text"))

    # 2. ответ текстом «1 ложка»
    m_ans = M(uid, "1 ложка")
    await bot._handle_message_locked(m_ans)
    check("порция и сахар попали в расчёт",
          "300" in captured.get("details", "") and "сахар 1" in captured.get("details", ""),
          captured.get("details"))
    conn = database._connect()
    row = dict(conn.execute("SELECT calories, sugar FROM food_log WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone())
    conn.close()
    check("калории выросли на сахар", row["calories"] == 27 and row["sugar"] == 6, row)

    # 3. «чай 300 без сахара» — вопросов нет
    bot._pending_clarification.pop(uid, None)
    m2 = M(uid, "чай 300 без сахара")
    await bot._handle_message_locked(m2)
    check("если сахар указан — не переспрашивает",
          not any("сахар" in t.lower() and "скажи" in t.lower() for t in m2.sent), m2.sent[-1][:70])
    check("записано без сахара", row is not None and "без сахара" in captured.get("details", ""), captured.get("details"))

    # 4. вода — без вопроса про сахар
    bot._pending_clarification.pop(uid, None)
    m3 = M(uid, "вода 300")
    await bot._handle_message_locked(m3)
    check("на воду сахар не спрашивает",
          not any("скажи, как пил" in t for t in m3.sent), m3.sent[-1][:70])

    # 5. ответ текстом «нет» = без сахара
    bot._pending_clarification.pop(uid, None)
    m4 = M(uid, "капучино 200")
    await bot._handle_message_locked(m4)
    check("на капучино спрашивает сахар", uid in bot._pending_clarification)
    m5 = M(uid, "нет")
    await bot._handle_message_locked(m5)
    check("«нет» понято как без сахара", "без сахара" in captured.get("details", ""), captured.get("details"))

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
