"""Тёплый вечер: ИИ-текст, запасной вариант и касания."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b14.db")
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
        self.sent = []
    async def answer(self, text, **kw): self.sent.append(text); return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


def make_user(uid):
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("name", "Дим"), ("week", 2), ("gender", "М"), ("height", 196),
                 ("weight", 146), ("age", 52), ("lifestyle", "сидячий")]:
        database.save_answer(uid, k, v)


async def main():
    database.init_db()

    # 1. ИИ включён: берём его текст и его касания
    make_user(7001)
    bot.ai.evening_messages = lambda ctx: {
        "intro": "Дим, вечер твой — просто чередуй бокал с водой.",
        "touches": ["Первое касание от ИИ.", "Второе касание от ИИ."]}
    m = M(7001, bot.BTN_EVENING)
    await bot._handle_message_locked(m)
    check("вступление взято у ИИ", "чередуй бокал с водой" in m.sent[-1], m.sent[-1][:70])
    check("служебные фразы не подставились", m.sent[-1] != bot.EVENING_INTRO)
    check("касания сохранены", bot._evening[7001]["phrases"] == ["Первое касание от ИИ.", "Второе касание от ИИ."])

    bot.ai.calculate_nutrition = lambda d, det: {
        "dish": "Виски", "weight": 50, "calories": 115, "protein": 0, "fat": 0,
        "carbs": 0, "sugar": 0, "bad_fat": 0, "salt": 0, "is_liquid": True, "ml": 50}
    bot.ai.split_components = lambda t: [t]
    bot.ai.get_questions_for_ai = lambda t: {"dish": "Виски", "questions": []}

    m = M(7001, "виски 50")
    await bot._handle_message_locked(m)
    check("после записи — касание от ИИ", "Первое касание от ИИ." in m.sent[-1], m.sent[-1][-60:])

    m = M(7001, "вино 150")
    await bot._handle_message_locked(m)
    check("второе касание тоже от ИИ", "Второе касание от ИИ." in m.sent[-1], m.sent[-1][-60:])

    m = M(7001, "пиво 500")
    await bot._handle_message_locked(m)
    check("третьего касания нет — прощание",
          "Второе касание" not in m.sent[-1] and "не отвлекаю" in m.sent[-1], m.sent[-1][-60:])

    # 2. ИИ не ответил: запасной вариант не ломает сценарий
    make_user(7002)
    bot.ai.evening_messages = lambda ctx: None
    m = M(7002, bot.BTN_EVENING)
    await bot._handle_message_locked(m)
    check("без ИИ работает запасной текст", "Тёплый вечер" in m.sent[-1] or "вечера" in m.sent[-1].lower(),
          m.sent[-1][:70])
    check("запасные касания на месте", len(bot._evening[7002]["phrases"]) >= 1)

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
