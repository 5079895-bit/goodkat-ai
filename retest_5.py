"""Перепроверка проблемных случаев: составные и запеканка."""
import os, asyncio, json, tempfile

os.environ.setdefault("BOT_TOKEN", "123456:TEST")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "retest.db")
import bot

CASES = ["пюре с котлетой и салат", "рис с овощами и рыбой",
         "творожная запеканка 150", "гречка с курицей", "макароны с сыром и сосиской"]


class M:
    def __init__(self, uid, text=None):
        self.from_user = type("U", (), {"id": uid})()
        self.text = text; self.photo = None; self.caption = None
        self.chat = type("C", (), {"id": uid})(); self.message_id = 1
        self.sent = []
    async def answer(self, text, **kw): self.sent.append(text); return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


def auto_answer(q):
    ql = (q or "").lower().replace("ё", "е")
    if "zero" in ql or "обычная или" in ql: return "обычная"
    if "жирност" in ql: return "2,5"
    if "мяс" in ql: return "курица"
    if "приготов" in ql or "жарен" in ql: return "жареная"
    if "на молоке или" in ql: return "на молоке"
    if "майонез" in ql: return "без майонеза"
    if "рыб" in ql: return "треска"
    if "сахар" in ql: return "1 чайная ложка"
    if "штук" in ql: return "1"
    if "сколько" in ql or "грамм" in ql or "мл" in ql: return "200"
    return "не знаю"


async def main():
    database.init_db()
    for i, text in enumerate(CASES):
        uid = 4000 + i
        today = database._get_user_date(uid, 3)
        database.create_user(uid); database.set_step(uid, 10)
        for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                     ("age", 45), ("lifestyle", "сидячий")]:
            database.save_answer(uid, k, v)

        m = M(uid, text)
        await bot._handle_message_locked(m)
        asked = []
        for _ in range(6):
            pending = bot._pending_clarification.get(uid)
            if not pending:
                break
            q = pending["questions"][pending["current_index"]]
            asked.append(q)
            m = M(uid, auto_answer(q))
            await bot._handle_message_locked(m)
            if "записал" in m.sent[-1]:
                break

        food = database.get_last_food(uid, today) or {}
        print(f"{text:30} → {str(food.get('dish'))[:40]:42} {food.get('calories')} ккал, "
              f"{food.get('weight')} | вопросов: {len(asked)}")
        for q in asked:
            print(f"      ? {q}")

asyncio.run(main())
