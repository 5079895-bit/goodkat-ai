"""Мясо и рыба: способ приготовления и сырой/готовый вес."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "meat.db")
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


def answer_for(q):
    ql = q.lower().replace("ё", "е")
    if "приготов" in ql:
        return None  # подставляется сценарием
    if "какая рыба" in ql or "из какого мяса" in ql:
        return "треска" if "рыб" in ql else "свинина"
    if "какая часть" in ql:
        return "грудка"
    if "скольк" in ql or "грамм" in ql:
        return "200"
    return "не знаю"


async def run(uid, script):
    for i, line in enumerate(script):
        if i == 0:
            bot._pending_clarification.pop(uid, None)
        m = M(uid, line)
        await bot._handle_message_locked(m)
        print(f"    {line!r:26} -> " + m.sent[-1].replace("\n", " ")[:110])


async def main():
    database.init_db()
    scenarios = [
        ("шашлык свиной 200", "жареный"),
        ("рыба 150", "сырая"),
        ("куриная грудка 150", "сырая"),
        ("стейк 250", "жареный"),
        ("шашлык", "не знаю"),
    ]
    for i, (dish, cooking) in enumerate(scenarios):
        uid = 8000 + i
        database.create_user(uid); database.set_step(uid, 10)
        for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                     ("age", 45), ("lifestyle", "сидячий")]:
            database.save_answer(uid, k, v)
        print(f"=== {dish}")
        m = M(uid, dish)
        await bot._handle_message_locked(m)
        print(f"    {dish!r:26} -> " + m.sent[-1].replace("\n", " ")[:110])
        for _ in range(3):
            pending = bot._pending_clarification.get(uid)
            if not pending:
                break
            q = pending["questions"][pending["current_index"]]
            a = cooking if "приготов" in q.lower() else answer_for(q)
            m = M(uid, a)
            await bot._handle_message_locked(m)
            print(f"    {a!r:26} -> " + m.sent[-1].replace("\n", " ")[:110])
            if "записал" in m.sent[-1]:
                break
        print()

asyncio.run(main())
