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

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
