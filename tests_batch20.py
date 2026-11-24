"""Вторая неделя: цель — диапазон похудения, а не поддержания. Кнопки капсом."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b20.db")
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
        self.sent = []
    async def answer(self, text, **kw): self.sent.append(text); return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


async def main():
    database.init_db()
    uid = 9200
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 52), ("lifestyle", "сидячий"), ("name", "Дим")]:
        database.save_answer(uid, k, v)
    user = database.get_user(uid)
    norms = bot._calc_norms(user)
    today = database._get_user_date(uid, 3)

    # профиль, на котором пользователь ждал 2400–2600 вместо 3000
    demo = bot._calc_norms({"weight": 125, "height": 178, "age": 52, "gender": "М", "lifestyle": "умеренный"})
    check("поддержание 3000 → похудение 2400–2600",
          (demo["support_high"], demo["loss_low"], demo["loss_high"]) == (3000, 2400, 2600),
          (demo["support_high"], demo["loss_low"], demo["loss_high"]))

    check("цель похудения ниже поддержания", norms["loss_high"] < norms["support_low"],
          (norms["loss_low"], norms["loss_high"], norms["support_low"], norms["support_high"]))

    database.add_food(uid, today, "Борщ", 624, 20, 20, 60, 5, 5, 400)
    line = bot._day_summary_lines(uid, today, user)
    check("сводка: диапазон похудения", f"{norms['loss_low']}–{norms['loss_high']}" in line, line)
    check("сводка: нет ккал поддержания", f"{norms['support_high']} ккал" not in line, line)
    pct = bot._calc_percent_range(624, norms["loss_low"], norms["loss_high"])
    check("сводка: процент диапазоном", f"({pct}%)" in line, line)
    check("процент: меньший к верхней границе", pct.split("–")[0] == str(min(100, round(624 / norms['loss_high'] * 100))), pct)

    # запись еды на второй неделе тоже показывает диапазон
    m = M(uid, "яблоко 100")
    bot.ai.split_components = lambda t: [t]
    bot.ai.get_questions_for_ai = lambda t: {"dish": t, "questions": []}
    bot.ai.calculate_nutrition = lambda d, det: {
        "dish": "Яблоко", "weight": 100, "calories": 52, "protein": 0.3, "fat": 0.2,
        "carbs": 14, "sugar": 10, "bad_fat": 0, "salt": 0, "is_liquid": False, "ml": None}
    await bot._handle_message_locked(m)
    saved = m.sent[-1]
    check("после записи: диапазон", f"{norms['loss_low']}–{norms['loss_high']} ккал" in saved, saved)

    # кнопки капсом
    check("кнопка вечера капсом", bot.BTN_EVENING == "🥂 ТЁПЛЫЙ ВЕЧЕР С БОКАЛОМ", bot.BTN_EVENING)
    check("кнопка меню капсом", bot.BTN_MENU_SEARCH == "🐾 ПОИЩЕМ ПО МЕНЮ", bot.BTN_MENU_SEARCH)
    check("кнопка не дома капсом", bot.BTN_EAT_OUT == "🐾 ПОЕДИМ НЕ ДОМА", bot.BTN_EAT_OUT)

    # текст «Котик рядом»
    m2 = M(uid, bot.BTN_KOTIK)
    await bot._handle_message_locked(m2)
    check("котик: новый текст", "по питанию" in m2.sent[-1] and "хорошего отдыха" in m2.sent[-1], m2.sent[-1])

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
