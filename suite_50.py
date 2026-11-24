"""Живой прогон 50 блюд: простые, составные, молочные, сложные, напитки."""
import os, asyncio, json, tempfile, time

os.environ.setdefault("BOT_TOKEN", "123456:TEST")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "suite50.db")
import bot

CASES = {
    "простые": [
        "борщ 300", "гречка 200", "рис 150", "макароны 200", "яблоко 150",
        "банан", "яйцо вареное 2", "хлеб 50", "сыр 30", "куриная грудка 150",
    ],
    "составные": [
        "пюре с котлетой и салат", "борщ и хлеб", "гречка с курицей",
        "рис с овощами и рыбой", "макароны с сыром и сосиской", "оливье 200",
        "шаурма с курицей", "пельмени 250", "плов 300", "суп с фрикадельками 350",
    ],
    "молочные": [
        "кефир 250", "молоко 200", "творог 150", "йогурт 125", "сметана 20",
        "ряженка 250", "айран 300", "сырники 3", "творожная запеканка 150", "простокваша 200",
    ],
    "сложные": [
        "котлета 100", "плов 300", "шашлык свиной 200", "гуляш 250", "пицца 300",
        "паста карбонара 300", "салат цезарь 250", "овсянка на молоке 250",
        "картофель жареный 200", "суп харчо 350",
    ],
    "напитки": [
        "чай 300", "кофе 200", "капучино", "латте", "кола", "сок 250",
        "компот 250", "морс 250", "квас 500", "какао 200",
    ],
}


class M:
    def __init__(self, uid, text=None):
        self.from_user = type("U", (), {"id": uid})()
        self.text = text; self.photo = None; self.caption = None
        self.chat = type("C", (), {"id": uid})(); self.message_id = 1
        self.sent = []
    async def answer(self, text, **kw): self.sent.append(text); return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


def auto_answer(q: str) -> str:
    ql = (q or "").lower().replace("ё", "е")
    if "zero" in ql or "обычная или" in ql:
        return "обычная"
    if "свежевыж" in ql or "пакетир" in ql:
        return "свежевыжатый"
    if "сладкий или" in ql:
        return "без сахара"
    if "сахар" in ql:
        return "1 чайная ложка"
    if "какое молоко" in ql:
        return "обычное"
    if "жирност" in ql:
        return "2,5"
    if "мяс" in ql:
        return "курица"
    if "приготов" in ql or "жарен" in ql:
        return "жареная"
    if "на молоке или" in ql:
        return "на молоке"
    if "майонез" in ql:
        return "без майонеза"
    if "суп" in ql and "какой" in ql:
        return "куриный"
    if "штук" in ql:
        return "1"
    if "сколько" in ql or "грамм" in ql or "мл" in ql:
        return "200"
    return "не знаю"


sem = asyncio.Semaphore(3)
results = []


async def run_case(group, text, idx):
    uid = 3000 + idx
    today = database._get_user_date(uid, 3)
    asked, answers, replies = [], [], []
    async with sem:
        database.create_user(uid)
        database.set_step(uid, 10)
        for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                     ("age", 45), ("lifestyle", "сидячий")]:
            database.save_answer(uid, k, v)

        m = M(uid, text)
        await bot._handle_message_locked(m)
        replies.append(m.sent[-1])

        for _ in range(4):
            pending = bot._pending_clarification.get(uid)
            if not pending:
                break
            q = pending["questions"][pending["current_index"]]
            a = auto_answer(q)
            asked.append(q)
            answers.append(a)
            m = M(uid, a)
            await bot._handle_message_locked(m)
            replies.append(m.sent[-1])
            if "записал" in m.sent[-1]:
                break

        food = database.get_last_food(uid, today) or {}
        results.append({
            "group": group, "input": text,
            "asked": asked, "answers": answers,
            "dish": food.get("dish"),
            "kcal": food.get("calories"),
            "weight": food.get("weight"),
            "liquid": food.get("is_liquid"),
            "ml": food.get("ml"),
            "last_reply": replies[-1][:160],
        })


async def main():
    database.init_db()
    started = time.time()
    tasks = []
    idx = 0
    for group, items in CASES.items():
        for text in items:
            tasks.append(run_case(group, text, idx))
            idx += 1
    await asyncio.gather(*tasks)

    with open("suite50_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    print(f"Готово за {time.time() - started:.0f} с, сценариев: {len(results)}\n")
    for group in CASES:
        rows = [r for r in results if r["group"] == group]
        print(f"=== {group} ({len(rows)})")
        for r in rows:
            q = len(r["asked"])
            print(f"  {r['input']:28} → {str(r['dish'])[:34]:36} {r['kcal']} ккал, {r['weight']} "
                  f"{'мл' if r['liquid'] else 'г'} | вопросов: {q}")

asyncio.run(main())
