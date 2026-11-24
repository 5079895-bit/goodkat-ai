"""Проверки: до трёх вопросов, по одному в сообщении."""
import os, asyncio, tempfile, json
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b12.db")
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
        self.html_text = ""; self.sent = []; self.markup = None
    async def answer(self, text, **kw):
        self.sent.append(text); return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


async def main():
    # потолок в самом ИИ: 5 вопросов -> 3
    class R:
        def __init__(self, c): self.choices = [type("C", (), {"message": type("M", (), {"content": c})})]
    class Comp:
        def create(self, **k):
            return R(json.dumps({"dish": "пицца", "questions": ["1", "2", "3", "4", "5"]}))
    class Cl:
        class chat:
            class completions:
                @staticmethod
                def create(**k): return R(json.dumps({"dish": "пицца", "questions": ["1", "2", "3", "4", "5"]}))
    real = ai.client
    ai.client = Cl()
    r = ai.get_questions_for_ai("пицца")
    ai.client = real
    check("ИИ не отдаёт больше трёх вопросов", len(r["questions"]) == 3, r["questions"])

    database.init_db()
    uid = 303
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 180), ("weight", 90),
                 ("age", 40), ("lifestyle", "умеренный")]:
        database.save_answer(uid, k, v)

    captured = {}
    def fake(dish, details):
        captured["details"] = details
        return {"dish": dish, "weight": 300, "calories": 400, "protein": 20, "fat": 15,
                "carbs": 40, "sugar": 0, "bad_fat": 0, "salt": 1, "is_liquid": False, "ml": None}
    bot.ai.calculate_nutrition = fake
    bot.ai.split_components = lambda t: [t]
    bot.ai.get_questions_for_ai = lambda t: {
        "dish": "пицца", "questions": ["Какая начинка?", "Сколько сыра?", "Тонкое или пышное тесто?"]}

    m = M(uid, "пицца 300 г")
    await bot._handle_message_locked(m)
    check("первый вопрос задан", "Какая начинка" in m.sent[-1], m.sent[-1][:60])

    m2 = M(uid, "пепперони")
    await bot._handle_message_locked(m2)
    check("второй вопрос задан после ответа", "Сколько сыра" in m2.sent[-1], m2.sent[-1][:60])

    m3 = M(uid, "много")
    await bot._handle_message_locked(m3)
    check("третий вопрос задан", "Тонкое или пышное" in m3.sent[-1], m3.sent[-1][:60])

    m4 = M(uid, "тонкое")
    await bot._handle_message_locked(m4)
    check("после третьего ответа — запись", "🔥 400 ккал" in m4.sent[-1], m4.sent[-1][:70])
    check("все три ответа дошли до расчёта",
          all(w in captured.get("details", "") for w in ("пепперони", "много", "тонкое")),
          captured.get("details"))
    check("четвёртого вопроса не было",
          not any("Сколько примерно" in t for t in m2.sent + m3.sent))

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
