"""Проверки: удаление обновляет экран, кнопка «Исправить» на месте."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b9.db")
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
        self.html_text = "Отлично, записал: X\n\n📊 За сегодня: 500 из 2600 ккал"
        self.sent = []; self.markup = None; self.edited = None; self.edit_markup = "?"
    async def answer(self, text, **kw):
        self.sent.append(text)
        if kw.get("reply_markup") is not None: self.markup = kw["reply_markup"]
        return self
    async def edit_text(self, text, **kw):
        self.edited = text
        self.edit_markup = kw.get("reply_markup", "нет ключа")
        self.sent.append(text)
        return self
    async def edit_reply_markup(self, reply_markup=None): return self


def cb_for(uid, data):
    cb = type("CB", (), {})()
    cb.from_user = type("U", (), {"id": uid})()
    cb.message = M(uid)
    cb.data = data
    cb.answer = lambda *a, **k: asyncio.sleep(0)
    return cb


async def main():
    # кнопка «Исправить» снова привязана к своему обработчику
    src = open("bot.py", encoding="utf-8").read()
    check("«Исправить» ведёт на cb_fix_last",
          '@dp.callback_query(F.data == "fix_last")\nasync def cb_fix_last' in src)
    check("«Исправить» больше не попадает в обработчик сахара",
          '@dp.callback_query(F.data == "fix_last")\nasync def cb_sugar' not in src)

    database.init_db()
    uid = 313
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 180), ("weight", 90),
                 ("age", 40), ("lifestyle", "умеренный")]:
        database.save_answer(uid, k, v)
    today = database._get_user_date(uid, 3)
    database.add_food(uid, today, "Каша", 200, 6, 7, 30, 0, 0, 250, is_liquid=0, ml=None)
    database.add_food(uid, today, "Борщ", 300, 9, 12, 20, 0, 0, 300, is_liquid=0, ml=None)

    # удаление
    cb = cb_for(uid, "delete_last")
    await bot.cb_delete_last(cb)

    text = cb.message.edited or ""
    check("сообщение переписано, а не дополнено", text.startswith("🗑 Запись удалена: <b>Борщ</b>"), text[:60])
    check("сводки на экране не осталось", "За сегодня" not in text and "из 2600" not in text, text)
    check("кнопки у записи убраны", cb.message.edit_markup is None, cb.message.edit_markup)

    # удаление последней — экран показывает «пусто»
    cb2 = cb_for(uid, "delete_last")
    await bot.cb_delete_last(cb2)
    check("после удаления — только факт удаления",
          (cb2.message.edited or "").startswith("🗑 Запись удалена") and "За сегодня" not in (cb2.message.edited or ""),
          cb2.message.edited)

    # данных нет
    cb3 = cb_for(uid, "delete_last")
    await bot.cb_delete_last(cb3)
    check("если удалять нечего — честно говорит", any("Не нашёл" in t for t in cb3.message.sent), cb3.message.sent)

    # «Исправить» освежает экран и просит ввести заново
    database.add_food(uid, today, "Плов", 400, 12, 14, 50, 0, 0, 300, is_liquid=0, ml=None)
    cb4 = cb_for(uid, "fix_last")
    await bot.cb_fix_last(cb4)
    check("«Исправить» переписал сообщение", (cb4.message.edited or "").startswith("✏️ Запись убрана: <b>Плов</b>"),
          (cb4.message.edited or "")[:50])
    check("и попросил ввести заново", any("заново" in t for t in cb4.message.sent), cb4.message.sent[-1][:60])
    check("запись действительно удалена", database.get_day_summary(uid, today) is None)

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
