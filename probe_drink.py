"""Напиток: объём и сахар из свободного ответа."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "drink.db")
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
    uid = 906
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid, k, v)

    cases = [("латте", "250 и 1"), ("чай", "250 2"), ("кола", "0,5 л обычная"), ("капучино", "300 без сахара")]
    for drink, answer in cases:
        bot._pending_clarification.pop(uid, None)
        m = M(uid, drink)
        await bot._handle_message_locked(m)
        print(f"  {drink!r:11} -> " + m.sent[-1].replace("\n", " ")[:80])
        m2 = M(uid, answer)
        await bot._handle_message_locked(m2)
        print(f"  {'':11} ← {answer!r:16} " + m2.sent[-1].split("\n")[0][:90] + " | " + m2.sent[-1].split("\n")[1][:40])

asyncio.run(main())
