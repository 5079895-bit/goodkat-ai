"""«Виски с колой» — один напиток: спрашиваем объём и Zero, не разбиваем на компоненты."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b17.db")
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
    # 1. склонения: «колой», «колы» — тот же сахарный напиток
    for t in ("виски с колой", "ром с колой 0,5 л", "колой 250", "пепси 0,5", "джин с тоником"):
        check(f"спрашиваем сахар: {t}", bot._needs_sugar_question(t) is True)
    check("«колбаса» — не напиток", bot._needs_sugar_question("колбаса 100") is False)
    check("вид вопроса — обычная/Zero", bot._sugar_kind("виски с колой") == "sweet")
    check("вид вопроса — обычная/Zero (тоник)", bot._sugar_kind("джин с тоником") == "sweet")

    # 2. смесь не разбивается на компоненты
    database.init_db()
    bot.ai.split_components = lambda t: ["виски", "кола"]
    bot.ai.calculate_nutrition = lambda d, det: {
        "dish": "Виски с колой", "weight": 250, "calories": 200, "protein": 0, "fat": 0,
        "carbs": 21, "sugar": 21, "bad_fat": 0, "salt": 0, "is_liquid": True, "ml": 250}

    uid = 7700
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid, k, v)

    m = M(uid, "виски с колой")
    await bot._handle_message_locked(m)
    check("первый вопрос — объём", "миллилитр" in m.sent[-1].lower() or "мл" in m.sent[-1].lower(),
          m.sent[-1][:80])
    check("не спросил «виски» отдельно", "виски" not in m.sent[-1].lower().replace("виски с колой", ""),
          m.sent[-1][:80])

    m2 = M(uid, "250")
    await bot._handle_message_locked(m2)
    check("второй вопрос — обычная или Zero", "zero" in m2.sent[-1].lower(), m2.sent[-1][:80])

    m3 = M(uid, "обычная")
    await bot._handle_message_locked(m3)
    reply = m3.sent[-1]
    check("записал одним напитком", "250 мл" in reply, reply.split("\n")[0][:80])
    check("калории смеси, а не виски", "200" in reply, reply.split("\n")[1][:40] if "\n" in reply else "")

    # 3. Zero тоже принимается
    uid2 = 7701
    database.create_user(uid2); database.set_step(uid2, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid2, k, v)
    m4 = M(uid2, "ром с колой 0,5 л")
    await bot._handle_message_locked(m4)
    check("объём назван — сразу про Zero", "zero" in m4.sent[-1].lower(), m4.sent[-1][:80])

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
