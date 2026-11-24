"""Напитки: раздельные вопросы по очереди."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "drink2.db")
import bot


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
    uid = 907
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid, k, v)

    scripts = [
        ("латте", ["250", "1", "обычное"]),
        ("чай", ["300", "без сахара"]),
        ("кола", ["0,5 л", "zero"]),
        ("сок", ["250", "свежевыжатый"]),
    ]
    for drink, answers in scripts:
        bot._pending_clarification.pop(uid, None)
        print(f"  === {drink}")
        m = M(uid, drink)
        await bot._handle_message_locked(m)
        print("     ? " + m.sent[-1].replace("\n", " ")[:100])
        for a in answers:
            m = M(uid, a)
            await bot._handle_message_locked(m)
            print(f"     ← {a!r:16} " + m.sent[-1].replace("\n", " ")[:120])

asyncio.run(main())
