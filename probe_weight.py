"""Что бот делает, когда вес/объём не назван (живой ИИ)."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "probe.db")
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
    uid = 902
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid, k, v)

    cases = [
        ("кефир", "300"),
        ("молоко", "не знаю"),
        ("котлета", "200"),
        ("банан", "1"),
        ("сыр", "30"),
    ]
    for dish, answer in cases:
        bot._pending_clarification.pop(uid, None)
        m = M(uid, dish)
        await bot._handle_message_locked(m)
        print(f"  {dish!r:10} -> " + m.sent[-1].replace("\n", " ")[:90])
        m2 = M(uid, answer)
        await bot._handle_message_locked(m2)
        print(f"  {'':10} → {answer!r:10} " + m2.sent[-1].replace("\n", " ")[:110])

asyncio.run(main())
