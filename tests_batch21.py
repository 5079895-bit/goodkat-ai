"""Меню по фото: один напиток в варианте, выбор одного блюда записывает одно блюдо."""
import os, asyncio, tempfile
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b21.db")
import bot

ok = []
def check(name, cond, detail=""):
    ok.append((name, cond))
    print(("PASS  " if cond else "FAIL  ") + name + ((" | " + str(detail)) if detail else ""))


class FakeBot:
    async def get_file(self, fid): return type("F", (), {"file_path": "photos/x.jpg"})()
    async def download_file(self, path, dest): open(dest, "wb").write(b"x")


bot.bot = FakeBot()


class Photo:
    file_id = "m1"; file_unique_id = "mu1"; width = 800; height = 600


class M:
    def __init__(self, uid, text=None, photo=False):
        self.from_user = type("U", (), {"id": uid})()
        self.text = text; self.photo = [Photo()] if photo else None; self.caption = None
        self.chat = type("C", (), {"id": uid})(); self.message_id = 1
        self.sent = []
    async def answer(self, text, **kw): self.sent.append(text); return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


async def main():
    database.init_db()
    uid = 9300
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 196), ("weight", 146),
                 ("age", 52), ("lifestyle", "сидячий"), ("name", "Дима")]:
        database.save_answer(uid, k, v)
    today = database._get_user_date(uid, 3)

    # 1. два напитка в одном варианте — остаётся один
    v = {"dish": "Капучино + Американо + Круасан", "calories": 405,
         "items": [{"name": "Капучино", "kind": "напиток", "calories": 80},
                   {"name": "Американо", "kind": "напиток", "calories": 5},
                   {"name": "Круасан", "kind": "десерт", "calories": 320}]}
    fixed = bot._fix_menu_variant(v)
    names = [i["name"] for i in fixed["items"]]
    check("два напитка → один", names == ["Капучино", "Круасан"], names)
    check("название пересобрано", fixed["dish"] == "Капучино + Круасан", fixed["dish"])
    check("калории пересчитаны", fixed["calories"] == 400, fixed["calories"])

    # 2. повтор одной позиции убирается
    v2 = {"dish": "Кофе + Кофе", "calories": 160,
          "items": [{"name": "Кофе", "kind": "напиток", "calories": 80},
                    {"name": "Кофе", "kind": "напиток", "calories": 80}]}
    fixed2 = bot._fix_menu_variant(v2)
    check("повтор убран", len(fixed2["items"]) == 1, fixed2["items"])

    # 3. правило записано в промпт
    prompt_src = open("ai.py", encoding="utf-8").read()
    check("в промпте: один напиток", "НЕ БОЛЬШЕ ОДНОГО напитка" in prompt_src)
    check("в промпте: два кофе — ошибка", "два кофе" in prompt_src)
    check("в промпте: состав варианта", "салат и/или суп и/или основное блюдо и/или напиток и/или десерт" in prompt_src)
    check("в промпте: категории позиций", '"kind" (салат / суп / основное / гарнир / напиток / десерт)' in prompt_src)

    # 4. выбрал словами одно блюдо — записалось одно, а не весь вариант
    calls = []
    def fake_calc(dish, details):
        calls.append((dish, details))
        return {"dish": dish, "weight": 200, "calories": 250, "protein": 30,
                "fat": 8, "carbs": 2, "sugar": 0, "bad_fat": 2, "salt": 1,
                "is_liquid": False, "ml": None}
    bot.ai.calculate_nutrition = fake_calc

    bot._active_menu[uid] = {
        "week": 2,
        "all_dishes": ["Салат Цезарь + Куриная грудка"],
        "all_items": [{"name": "Салат Цезарь"}, {"name": "Куриная грудка"}],
    }
    m = M(uid, "куриная грудка")
    await bot._handle_message_locked(m)
    saved = m.sent[-1]
    check("одно блюдо: считали только грудку", calls and calls[-1][0] == "Куриная грудка", calls)
    check("одно блюдо: в записи только грудка", "Куриная грудка" in saved and "Цезарь" not in saved, saved)

    # 5. выбрал вариант номером — пишется вариант целиком
    bot._active_menu[uid] = {
        "week": 2,
        "green": {"dish": "Салат Цезарь + Куриная грудка", "calories": 550, "weight": 400,
                  "protein": 40, "fat": 25, "carbs": 20},
        "all_dishes": ["Салат Цезарь + Куриная грудка"],
        "all_items": [{"name": "Салат Цезарь"}, {"name": "Куриная грудка"}],
    }
    m2 = M(uid, "1")
    await bot._handle_message_locked(m2)
    saved2 = "\n".join(m2.sent)
    check("вариант номером: оба блюда", "Салат Цезарь + Куриная грудка" in saved2 and "550" in saved2, saved2)

    # 6. меню: в ответе нет цифр и выбора 1/2/3
    bot._pending_menu_mode[uid] = {"waiting": True}
    bot.ai.analyze_menu_photo = lambda path: {"description": "Салат Цезарь 340; Куриная грудка 250; Капучино 80", "error": False}
    bot.ai.analyze_menu_and_build_traffic_light = lambda *a, **k: {
        "is_menu": True,
        "green": {"dish": "Куриная грудка + Капучино", "calories": 330, "weight": 400,
                  "protein": 40, "fat": 10, "carbs": 5,
                  "items": [{"name": "Куриная грудка", "kind": "основное", "calories": 250},
                            {"name": "Капучино", "kind": "напиток", "calories": 80}]},
        "yellow": None, "red": None}
    m3 = M(uid, photo=True)
    await bot._handle_message_locked(m3)
    menu_reply = m3.sent[-1]
    check("меню: просит написать, что выбрал", "Напиши, что выбрал" in menu_reply, menu_reply)
    check("меню: без номеров вариантов", "номер варианта" not in menu_reply and "«1»" not in menu_reply, menu_reply)
    bot._active_menu.pop(uid, None)

    # 7. написал блюдо не из меню → пишем как обычную еду
    bot._active_menu[uid] = {"week": 2, "all_dishes": ["Салат Цезарь"],
                             "all_items": [{"name": "Салат Цезарь"}]}
    bot.ai.split_components = lambda t: [t]
    bot.ai.get_questions_for_ai = lambda t: {"dish": t, "questions": ["Сколько примерно грамм?"]}
    m4 = M(uid, "пицца")
    await bot._handle_message_locked(m4)
    flow = "\n".join(m4.sent)
    check("не из меню: так и сказали", "нет в меню" in flow, flow)
    check("не из меню: перешли к записи еды", "грамм" in flow.lower(), flow)

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
