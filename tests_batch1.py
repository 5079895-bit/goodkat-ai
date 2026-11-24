"""Проверки пакета 1 (BUG-16,17,18,20,21,22,23) — дописываются к tests.py."""
import os, sys, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b1.db")
import bot

ok_all = []


def check(name, ok, detail=""):
    ok_all.append((name, ok))
    print(("PASS  " if ok else "FAIL  ") + name + ((" | " + str(detail)) if detail else ""))


class M:
    def __init__(self, uid, text=None):
        self.from_user = type("U", (), {"id": uid})()
        self.text = text; self.photo = None; self.caption = None
        self.chat = type("C", (), {"id": uid})(); self.message_id = 1
        self.html_text = ""; self.sent = []
    async def answer(self, text, **kw):
        self.sent.append(text); return self
    async def edit_text(self, text, **kw):
        self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None):
        self.sent.append("[кнопки убраны]"); return self


async def main():
    # ---------- BUG-16/17: fast-path без переспросов ----------
    cases = {
        "Чай 300": "300 мл",
        "Капучино 300": "300 мл",
        "Яйцо вареное 2 штуки": "110 г",
        "Борщ 300 г": "300 г",
        "Банан 1 штука": "100 г",
        "Пиво 0,5 л": "500 мл",
    }
    for text, expect_start in cases.items():
        got = bot._quick_details(text)
        check(f"1 шаг без вопросов: «{text}»", bool(got) and got.startswith(expect_start), got)

    check("неизвестное блюдо не уходит в fast-path", bot._quick_details("Плов по-узбекски с бараниной") is None)

    # ---------- BUG-22: «Записал» только после сохранения ----------
    src = open("bot.py", encoding="utf-8").read()
    check("«Записал:» больше не печатается до сохранения", "Записал:" not in src)
    check("вместо него «Понял:»", src.count('"Понял:') >= 4)

    # ---------- BUG-18: «Исправить» удаляет старую запись ----------
    database.init_db()
    uid = 700
    database.create_user(uid); database.set_step(uid, 10); database.save_answer(uid, "week", 2)
    today = database._get_user_date(uid, 3)
    database.add_food(uid, today, "Старый борщ", 500, 10, 20, 30, 0, 0, 300)

    cb = type("CB", (), {})()
    cb.from_user = type("U", (), {"id": uid})()
    cb.message = M(uid)
    cb.answer = lambda *a, **k: asyncio.sleep(0)
    await bot.cb_fix_last(cb)

    left = database.get_day_summary(uid, today)
    check("«Исправить» удалил старую запись", left is None, left)
    check("бот попросил ввести заново", any("заново" in t for t in cb.message.sent), cb.message.sent)

    # ---------- BUG-23: «Нет» не стирает текст ----------
    cb2 = type("CB", (), {})()
    cb2.from_user = type("U", (), {"id": uid})()
    cb2.message = M(uid)
    cb2.message.edit_text = None
    cb2.answer = lambda *a, **k: asyncio.sleep(0)
    await bot.cb_help_no(cb2)
    check("«Нет» убирает кнопки, а не текст ответа", "[кнопки убраны]" in cb2.message.sent)
    check("одна реплика возврата вместо двух", len(cb2.message.sent) == 2, len(cb2.message.sent))

    # ---------- BUG-21: режим неполного дня ----------
    captured = {}
    def fake_summary(user, summary, liquid, partial=False):
        captured["partial"] = partial
        return "Понял."
    bot.ai.generate_day_summary = fake_summary
    m = M(uid, "итог")
    database.add_food(uid, today, "Кофе", 90, 3, 3, 5, 0, 0, 200, is_liquid=1, ml=200)
    await bot._send_day_summary(m, uid)
    check("малый день уходит в режим «в бегах»", captured.get("partial") is True, captured)

    # ---------- BUG-20: ответ «Обычное» без контекста ----------
    m2 = M(uid, "Обычное")
    await bot._handle_message_locked(m2)
    check("одиночное «Обычное» не записывается как блюдо",
          "капучино 200" in m2.sent[-1].lower() or "целиком" in m2.sent[-1].lower(), m2.sent[-1][:80])

    bad = [n for n, ok in ok_all if not ok]
    print(f"\nИтог: {len(ok_all)} проверок, провалено {len(bad)}")
    for n in bad:
        print("  ✗", n)

asyncio.run(main())
