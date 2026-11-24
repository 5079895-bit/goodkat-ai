"""Мясо и рыба: вопрос про способ приготовления и сырой вес."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b15.db")
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
    # 1. определение
    check("рыба без способа — нужен вопрос", ai.needs_cooking_question("рыба 150", []) is True)
    check("мясо без способа — нужен вопрос", ai.needs_cooking_question("мясо 200", []) is True)
    check("шашлык без способа — нужен вопрос", ai.needs_cooking_question("шашлык свиной 200", []) is True)
    check("«рыба жареная» — вопрос не нужен", ai.needs_cooking_question("рыба жареная 150", []) is False)
    check("«курица варёная» — вопрос не нужен", ai.needs_cooking_question("курица вареная 150", []) is False)
    check("сыр — не мясо", ai.needs_cooking_question("сыр 30", []) is False)
    check("борщ — не мясо", ai.needs_cooking_question("борщ 300", []) is False)

    # 2. вопрос попадает в список и не вытесняет порцию
    q = ai.ensure_questions("рыба 150", [])
    check("вопрос про способ в списке", any("приготов" in x.lower() for x in q), q)
    q2 = ai.ensure_questions("котлета", ["Из какого мяса?"])
    check("порция осталась первой у мяса без веса", q2[0].startswith("Сколько"), q2)
    check("способ добавлен после порции", any("приготов" in x.lower() for x in q2), q2)

    # 3. средняя порция шашлыка больше не 300
    check("средняя порция шашлыка — 200 г", ai.STANDARDS.get("шашлык") == 200, ai.STANDARDS.get("шашлык"))

    # 4. живой сценарий: рыба 150 -> сырая
    database.init_db()
    uid = 9001
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid, k, v)

    bot.ai.get_questions_for_ai = lambda t: {"dish": t, "questions": ["Какая рыба (треска / лосось)?"]}
    bot.ai.split_components = lambda t: [t]
    bot.ai.calculate_nutrition = lambda d, det: {
        "dish": "Рыба (сырая)", "weight": 150, "calories": 158, "protein": 27, "fat": 5,
        "carbs": 0, "sugar": 0, "bad_fat": 0, "salt": 0, "is_liquid": False, "ml": None}

    m = M(uid, "рыба 150")
    await bot._handle_message_locked(m)
    check("бот спросил про рыбу и способ",
          "Какая рыба" in m.sent[-1], m.sent[-1][:80])

    m2 = M(uid, "треска")
    await bot._handle_message_locked(m2)
    check("после вида спрашивает способ приготовления",
          "приготов" in m2.sent[-1].lower(), m2.sent[-1][:80])

    m3 = M(uid, "сырая")
    await bot._handle_message_locked(m3)
    check("после ответа записал", "🔥" in m3.sent[-1], m3.sent[-1][:70])

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
