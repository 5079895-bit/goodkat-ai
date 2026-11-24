"""Живые сценарии: количество спрашивается, «не знаю» -> средний показатель."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "probe2.db")
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


async def run(uid, script):
    for line in script:
        bot._pending_clarification.pop(uid, None) if line == script[0] else None
        m = M(uid, line)
        await bot._handle_message_locked(m)
        print(f"    {line!r:22} -> " + m.sent[-1].replace("\n", " ")[:120])


async def main():
    database.init_db()
    uid = 903
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid, k, v)

    print("  молоко → не знаю → 2,5%")
    await run(uid, ["молоко", "не знаю", "2,5"])

    print("  кефир → не знаю")
    await run(uid, ["кефир", "не знаю"])

    print("  котлета → 200 → свинина → жареная")
    await run(uid, ["котлета", "200", "свинина", "жареная"])

    print("  банан → 1")
    await run(uid, ["банан", "1"])

asyncio.run(main())
