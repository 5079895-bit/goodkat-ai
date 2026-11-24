"""Проверка сценария «Поищем по меню» на живом ИИ."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "menu.db")
import bot


class M:
    def __init__(self, uid, text=None):
        self.from_user = type("U", (), {"id": uid})()
        self.text = text; self.photo = None; self.caption = None
        self.chat = type("C", (), {"id": uid})(); self.message_id = 1
        self.html_text = ""; self.sent = []
    async def answer(self, text, **kw): self.sent.append(text); return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


async def main():
    database.init_db()
    uid = 808
    database.create_user(uid); database.set_step(uid, 10); database.save_answer(uid, "week", 2)
    database.save_answer(uid, "gender", "М"); database.save_answer(uid, "height", 180)
    database.save_answer(uid, "weight", 90); database.save_answer(uid, "age", 40)
    database.save_answer(uid, "lifestyle", "умеренный")
    today = database._get_user_date(uid, 3)

    # 1. «Зайти красиво» -> «Поищем по меню»
    m0 = M(uid, bot.BTN_MENU)
    await bot._handle_message_locked(m0)
    print("1a) Зайти красиво:", m0.sent[-1][:80])
    m0 = M(uid, bot.BTN_MENU_SEARCH)
    await bot._handle_message_locked(m0)
    print("1b) Поищем по меню:", m0.sent[-1][:100])

    # 2. присылает меню текстом
    menu = ("Меню кафе: Борщ 350, Цезарь с курицей 420, Паста карбонара 650, "
            "Стейк из говядины 700, Картофель фри 300, Чизкейк 380, Американо 120, "
            "Латте 250, Раф 300, Салат овощной 180")
    m = M(uid, menu)
    await bot._handle_work(m, uid, menu)
    print("\n2) ответ на меню:")
    for line in m.sent: print("   ", line.replace("\n", " ")[:170])

    # 3. выбирает вариант
    m2 = M(uid, "зелёный")
    await bot._handle_work(m2, uid, "зелёный")
    print("\n3) выбор «зелёный»:")
    for line in m2.sent: print("   ", line.replace("\n", " ")[:170])

    conn = database._connect()
    rows = [dict(r) for r in conn.execute("SELECT dish, calories, weight FROM food_log WHERE user_id=?", (uid,))]
    conn.close()
    print("\n4) в базе:", rows)


asyncio.run(main())
