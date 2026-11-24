"""Итог дня: только вечером, кнопкой после 19:00."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b13.db")
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
        self.html_text = ""; self.sent = []; self.markup = None
    async def answer(self, text, **kw):
        self.sent.append(text)
        if kw.get("reply_markup") is not None: self.markup = kw["reply_markup"]
        return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


async def main():
    database.init_db()
    bot.ai.generate_day_summary = lambda *a, **k: "ИТОГ-ЗАГЛУШКА"

    def make_user(uid, offset):
        database.create_user(uid); database.set_step(uid, 10)
        for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                     ("age", 45), ("lifestyle", "сидячий"), ("utc_offset", offset)]:
            database.save_answer(uid, k, v)

    # день (offset 3 — сейчас ~11:30 МСК)
    make_user(601, 3)
    m = M(601, "итог")
    await bot._handle_message_locked(m)
    reply = m.sent[-1]
    check("днём итог не показывается", "ИТОГ-ЗАГЛУШКА" not in reply and "Твои итоги" not in reply, reply[:70])
    check("днём бот мягко объясняет про вечер", "после 19 часов" in reply and "отдельная кнопка" in reply, reply[:90])

    m2 = M(601, bot.BTN_SUMMARY)
    await bot._handle_message_locked(m2)
    check("кнопка днём тоже не даёт итог", "ИТОГ-ЗАГЛУШКА" not in m2.sent[-1])

    # вечер (offset 13 — сейчас ~21:30)
    make_user(602, 13)
    m3 = M(602, bot.BTN_SUMMARY)
    await bot._handle_message_locked(m3)
    check("вечером кнопка даёт итог",
          any("ИТОГ-ЗАГЛУШКА" in t or "ничего не записывал" in t for t in m3.sent), m3.sent[-1][:70])

    # меню: кнопка появляется только вечером
    rows_day = [[b.text for b in r] for r in bot._main_menu_keyboard({"utc_offset": None}).keyboard]
    check("днём в меню нет кнопки «ИТОГ ДНЯ»",
          all(bot.BTN_SUMMARY not in row for row in rows_day), rows_day)

    evening_user = database.get_user(602)
    rows_evening = [[b.text for b in r] for r in bot._main_menu_keyboard(evening_user).keyboard]
    check("вечером кнопка «ИТОГ ДНЯ» есть",
          any(bot.BTN_SUMMARY in row for row in rows_evening), rows_evening)

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
