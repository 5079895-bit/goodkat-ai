"""Почему яйца и сырники считаются как 2-3 грамма."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "egg.db")
import bot, ai

orig = ai.calculate_nutrition


def spy(dish, details):
    r = orig(dish, details)
    print(f"   CALC dish={dish!r} details={details!r} -> weight={r.get('weight')} kcal={r.get('calories')}")
    return r


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
    database.init_db()
    bot.ai.calculate_nutrition = spy
    for i, text in enumerate(("яйцо вареное 2", "сырники 3")):
        uid = 5000 + i
        database.create_user(uid); database.set_step(uid, 10)
        for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                     ("age", 45), ("lifestyle", "сидячий")]:
            database.save_answer(uid, k, v)
        print(f"--- {text}")
        m = M(uid, text)
        await bot._handle_message_locked(m)
        print("   ответ:", m.sent[-1].split("\n")[0])

asyncio.run(main())
