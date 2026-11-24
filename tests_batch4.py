"""Новый формат меню: калории по каждой позиции, без служебных слов."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b5.db")
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


MENU = {
    "is_menu": True,
    "week": 2,
    "green": {"dish": "Капучино + Круасан", "calories": 460,
              "items": [{"name": "Капучино", "calories": 140}, {"name": "Круасан", "calories": 320}],
              "weight": 250, "protein": 8, "fat": 25, "carbs": 45},
    "yellow": {"dish": "Салат Цезарь с курицей + Овощи тушёные с говядиной", "calories": 780,
               "items": [{"name": "Салат Цезарь с курицей", "calories": 340},
                         {"name": "Овощи тушёные с говядиной", "calories": 440}],
               "weight": 500, "protein": 40, "fat": 30, "carbs": 55},
    "red": {"dish": "Стейк из говядины + Картофель фри", "calories": 1000,
            "items": [{"name": "Стейк из говядины", "calories": 700}, {"name": "Картофель фри", "calories": 300}],
            "weight": 500, "protein": 55, "fat": 60, "carbs": 40},
}
NO_ITEMS = {"is_menu": True, "week": 2,
            "green": {"dish": "Салат овощной + Американо", "calories": 185, "weight": 450},
            "yellow": None, "red": None}
EMPTY = {"is_menu": True, "week": 2, "green": None, "yellow": None, "red": None}


async def main():
    database.init_db()
    uid = 616
    database.create_user(uid); database.set_step(uid, 10); database.save_answer(uid, "week", 2)
    database.save_answer(uid, "gender", "М"); database.save_answer(uid, "height", 180)
    database.save_answer(uid, "weight", 90); database.save_answer(uid, "age", 40)
    database.save_answer(uid, "lifestyle", "умеренный")

    bot.ai.analyze_menu_and_build_traffic_light = lambda *a, **k: MENU
    bot._pending_menu_mode[uid] = {"waiting": True}
    m = M(uid, "Меню: капучино, круасан, цезарь, овощи с говядиной, стейк, картофель фри")
    await bot._handle_work(m, uid, m.text)
    text = m.sent[-1]
    print("--- сообщение ---\n" + text + "\n-----------------")

    check("калории по каждой позиции, как в примере",
          "🐾 <b>Капучино</b> (140 ккал) + <b>Круасан</b> (320 ккал). Спокойно выбираем и всё равно продолжим худеть 💚" in text)
    check("вторая строка — та же схема",
          "🐾 <b>Салат Цезарь с курицей</b> (340 ккал) + <b>Овощи тушёные с говядиной</b> (440 ккал). "
          "Чуть плотнее, но лишнего не наберём 🐾" in text)
    check("третья строка без служебных цифр",
          "🐾 <b>Стейк из говядины</b> (700 ккал) + <b>Картофель фри</b> (300 ккал). "
          "Если очень хочется праздника. А завтра продолжим как обычно" in text)
    check("слов «похудения»/«поддержания» в тексте нет",
          "похудени" not in text.lower() and "поддержан" not in text.lower())
    check("подсказка выбора — без служебных слов", "«1», «2», «3»" in text)

    # выбор номером
    m2 = M(uid, "2")
    await bot._handle_work(m2, uid, "2")
    conn = database._connect()
    row = dict(conn.execute(
        "SELECT dish, calories FROM food_log WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone())
    conn.close()
    check("выбор «2» записал второй вариант", row["dish"].startswith("Салат Цезарь"), row)

    # старый ответ ИИ без items — запасной вариант
    bot.ai.analyze_menu_and_build_traffic_light = lambda *a, **k: NO_ITEMS
    bot._pending_menu_mode[uid] = {"waiting": True}
    m3 = M(uid, "Меню: салат, американо")
    await bot._handle_work(m3, uid, m3.text)
    check("без items бот показывает общее блюдо и сумму",
          "<b>Салат овощной + Американо</b> (185 ккал)" in m3.sent[-1], m3.sent[-1][:120])

    # пустое меню
    bot.ai.analyze_menu_and_build_traffic_light = lambda *a, **k: EMPTY
    bot._pending_menu_mode[uid] = {"waiting": True}
    m4 = M(uid, "Меню: только вода")
    await bot._handle_work(m4, uid, m4.text)
    check("пустое меню — честный текст", "ничего подходящего" in m4.sent[-1])

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
