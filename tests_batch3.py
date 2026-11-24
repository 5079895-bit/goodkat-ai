"""Пакет 3: навигация «Котик рядом» и FEAT-10 «Тёплый вечер с бокалом»."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b3.db")
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


async def send(uid, text):
    m = M(uid, text)
    await bot._handle_message_locked(m)
    return m


async def main():
    database.init_db()
    uid = 909
    database.create_user(uid); database.set_step(uid, 10); database.save_answer(uid, "week", 2)
    database.save_answer(uid, "gender", "Ж"); database.save_answer(uid, "height", 165)
    database.save_answer(uid, "weight", 60); database.save_answer(uid, "age", 30)
    database.save_answer(uid, "lifestyle", "умеренный")

    # еда без запросов к ИИ
    bot.ai.get_questions_for_ai = lambda t: {"dish": t, "questions": []}
    bot.ai.split_components = lambda t: [t]
    bot.ai.calculate_nutrition = lambda d, det: {
        "dish": d, "weight": 150, "calories": 200, "protein": 8, "fat": 9,
        "carbs": 20, "sugar": 0, "bad_fat": 0, "salt": 1, "is_liquid": False, "ml": None}

    # ---------- навигация: три кнопки в главном, по подменю в каждой ----------
    main_kb = bot._main_menu_keyboard({"utc_offset": 3})
    rows = [[b.text for b in row] for row in main_kb.keyboard]
    check("главное меню — три кнопки: еда / котик / зайти красиво",
          rows[:3] == [[bot.BTN_EAT], [bot.BTN_KOTIK], [bot.BTN_MENU]], rows)
    check("в главном меню нет кнопки «Вода»",
          all(bot.BTN_WATER not in row for row in rows), rows)

    kotik_rows = [[b.text for b in row] for row in bot._kotik_keyboard().keyboard]
    check("внутри «Котик рядом»: подскажи + тёплый вечер",
          kotik_rows == [[bot.BTN_HELP], [bot.BTN_EVENING], [bot.BTN_BACK]], kotik_rows)

    menu_rows = [[b.text for b in row] for row in bot._menu_keyboard().keyboard]
    check("внутри «Зайти красиво»: по меню + поедим не дома",
          menu_rows == [[bot.BTN_MENU_SEARCH], [bot.BTN_EAT_OUT], [bot.BTN_BACK]], menu_rows)

    m = await send(uid, bot.BTN_MENU)
    check("«Зайти красиво» открывает своё подменю", m.markup is not None and
          "за столиком" in m.sent[-1], m.sent[-1][:60])

    m = await send(uid, bot.BTN_KOTIK)
    check("кнопка «Котик рядом» открывает подменю", m.markup is not None and "Я рядом" in m.sent[-1], m.sent[-1][:70])
    kb = m.sent  # клавиатуру не проверяем по объекту, только факт ответа

    m = await send(uid, bot.BTN_MENU_SEARCH)
    check("«Поищем по меню» просит меню", any("Пришли меню" in t for t in m.sent), m.sent[-1][:60])
    check("режим меню включился", uid in bot._pending_menu_mode)

    m = await send(uid, bot.BTN_BACK)
    check("«Назад» возвращает главное меню", "Возвращаемся" in m.sent[-1])

    m = await send(uid, bot.BTN_EAT_OUT)
    check("«Поедим не дома» честно говорит, что это заглушка",
          "пока не умею" in m.sent[-1].lower(), m.sent[-1][:70])

    # ---------- тёплый вечер ----------
    m = await send(uid, bot.BTN_EVENING)
    check("вечер: одно напутствие на входе", "чередуй бокал с водой" in m.sent[-1])
    check("вечер: режим включён", uid in bot._evening, bot._evening.get(uid))

    today = database._get_user_date(uid, 3)
    touches = []
    for i in range(1, 4):
        m = await send(uid, f"вино {150 * i} мл")
        touches.append(m.sent[-1])
        database.add_food  # noqa

    check("вечер: 1-е касание после записи", bot.EVENING_TOUCHES[0] in touches[0])
    check("вечер: 2-е касание после записи", bot.EVENING_TOUCHES[1] in touches[1])
    check("вечер: третье касание — мягкий выход", bot.EVENING_BYE in touches[2])
    check("вечер: режим снят после выхода", uid not in bot._evening)

    m = await send(uid, "вино 150 мл")
    check("после выхода бот больше не комментирует",
          not any(t in m.sent[-1] for t in bot.EVENING_TOUCHES + (bot.EVENING_BYE,)))

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad:
        print("  ✗", n)

asyncio.run(main())
