"""Фото по новой логике: «Вижу: X. Верно?» → да → вес и детали → запись."""
import os, asyncio, tempfile, shutil
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import database
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "b19.db")
import bot

IMG = os.path.join(tempfile.mkdtemp(), "food.jpg")
open(IMG, "wb").write(b"\xff\xd8\xff\xe0test")


class FakeBot:
    async def get_file(self, fid): return type("F", (), {"file_path": "photos/x.jpg"})()
    async def download_file(self, path, dest): shutil.copy(IMG, dest)


bot.bot = FakeBot()


class Photo:
    file_id = "p1"; file_unique_id = "u1"; width = 800; height = 600


class M:
    def __init__(self, uid, text=None, photo=False):
        self.from_user = type("U", (), {"id": uid})()
        self.text = text; self.photo = [Photo()] if photo else None; self.caption = None
        self.chat = type("C", (), {"id": uid})(); self.message_id = 1
        self.sent = []
    async def answer(self, text, **kw): self.sent.append(text); return self
    async def edit_text(self, text, **kw): self.sent.append(text); return self
    async def edit_reply_markup(self, reply_markup=None): return self


ok = []
def check(name, cond, detail=""):
    ok.append((name, cond))
    print(("PASS  " if cond else "FAIL  ") + name + ((" | " + str(detail)) if detail else ""))


def make_user(uid):
    database.create_user(uid); database.set_step(uid, 10)
    for k, v in [("week", 2), ("gender", "М"), ("height", 178), ("weight", 95),
                 ("age", 45), ("lifestyle", "сидячий")]:
        database.save_answer(uid, k, v)


async def main():
    database.init_db()

    bot.ai.get_questions_for_ai = lambda t: {"dish": t, "questions": ["Сколько примерно грамм?"]}
    bot.ai.calculate_nutrition = lambda d, det: {
        "dish": "Куриная грудка с рисом", "weight": 350, "calories": 420, "protein": 35,
        "fat": 9, "carbs": 45, "sugar": 0, "bad_fat": 0, "salt": 0, "is_liquid": False, "ml": None}

    # 1. уверенно увидел — сначала название, без цифр
    uid = 9100; make_user(uid)
    bot.ai.analyze_photo = lambda path: {"is_food": True, "is_compound": False, "is_drink": False,
                                         "confident": True, "description": "Куриная грудка с рисом"}
    m = M(uid, photo=True)
    await bot._handle_photo(m, uid)
    reply = m.sent[-1]
    check("фото: сначала название", "Вижу: Куриная грудка с рисом" in reply, reply)
    check("фото: спросили «верно?»", "Верно?" in reply, reply)
    check("фото: цифр до «да» нет", "ккал" not in reply, reply)

    # 2. «да» → вопрос про вес, а не запись
    m2 = M(uid, "да")
    await bot._handle_message_locked(m2)
    q = m2.sent[-1]
    check("«да»: спросили вес", "грамм" in q.lower(), q)
    check("«да»: запись не сделана", (database.get_day_summary(uid, database._get_user_date(uid, 3)) or {}).get("calories", 0) == 0, q)

    # 3. вес → детали (как приготовлено) → запись
    m3 = M(uid, "350")
    await bot._handle_message_locked(m3)
    check("вес: спросили приготовление", "приготовлено" in m3.sent[-1].lower(), m3.sent[-1])
    m3b = M(uid, "жареное")
    await bot._handle_message_locked(m3b)
    saved = m3b.sent[-1]
    check("вес: записали 420 ккал", "420" in saved, saved)
    check("вес: записали 350 г", "350" in saved, saved)
    import sqlite3
    cnt = sqlite3.connect(database.DB_PATH).execute(
        "select count(*) from food_log where user_id=? and date=?", (uid, database._get_user_date(uid, 3))).fetchone()[0]
    check("вес: в базе одна запись", cnt == 1, cnt)

    # 4. «нет» → просим написать словами
    uid2 = 9101; make_user(uid2)
    bot.ai.analyze_photo = lambda path: {"is_food": True, "is_compound": False, "is_drink": False,
                                         "confident": True, "description": "Куриная грудка с рисом"}
    m4 = M(uid2, photo=True); await bot._handle_photo(m4, uid2)
    m5 = M(uid2, "нет"); await bot._handle_message_locked(m5)
    check("«нет»: просим написать, что съел или выпил", "съел или выпил" in m5.sent[-1], m5.sent[-1])
    check("«нет»: не спрашиваем «что пил?»", "пил?" not in m5.sent[-1].lower(), m5.sent[-1])
    check("«нет»: ничего не записали", (database.get_day_summary(uid2, database._get_user_date(uid2, 3)) or {}).get("calories", 0) == 0)

    # 5. видит еду, но не понял → «пока учусь»
    uid3 = 9102; make_user(uid3)
    bot.ai.analyze_photo = lambda path: {"is_food": True, "is_compound": False, "is_drink": False,
                                         "confident": False, "description": "что-то на тарелке"}
    m6 = M(uid3, photo=True); await bot._handle_photo(m6, uid3)
    check("не понял еду: «пока учусь»", "пока учусь" in m6.sent[-1], m6.sent[-1])

    # 6. видит напиток, но не понял → «пока учусь», без «что ты пил?» наугад
    bot.ai.analyze_photo = lambda path: {"is_food": True, "is_compound": False, "is_drink": True,
                                         "confident": False, "description": "стакан с тёмной жидкостью"}
    m7 = M(uid3, photo=True); await bot._handle_photo(m7, uid3)
    check("не понял напиток: «пока учусь»", "пока учусь" in m7.sent[-1] and "напиток" in m7.sent[-1], m7.sent[-1])

    # 7. не еда → «могу ошибаться»
    bot.ai.analyze_photo = lambda path: {"is_food": False, "is_compound": False, "is_drink": False,
                                         "confident": True, "description": "кот"}
    m8 = M(uid3, photo=True); await bot._handle_photo(m8, uid3)
    check("не еда: «могу ошибаться»", "могу ошибаться" in m8.sent[-1], m8.sent[-1])

    # 8. составное: после «да» считаем по компонентам, ничего не теряя
    uid4 = 9103; make_user(uid4)
    bot.ai.analyze_photo = lambda path: {"is_food": True, "is_compound": True, "is_drink": False,
                                         "confident": True, "name": "Суп, салат и мясо",
                                         "description": "Тарелка супа, миска салата и тарелка мяса"}
    bot.ai.split_components = lambda t: ["суп", "салат", "мясо"]
    def fake_calc(d, det):
        low = (d or "").lower()
        if "суп" in low:
            return {"dish": "суп", "weight": 300, "calories": 100, "protein": 4, "fat": 5, "carbs": 10,
                    "sugar": 2, "bad_fat": 1, "salt": 1, "is_liquid": False, "ml": None}
        if "салат" in low:
            return {"dish": "салат", "weight": 150, "calories": 50, "protein": 1, "fat": 3, "carbs": 4,
                    "sugar": 1, "bad_fat": 0, "salt": 0.3, "is_liquid": False, "ml": None}
        return {"dish": "мясо", "weight": 100, "calories": 200, "protein": 20, "fat": 12, "carbs": 0,
                "sugar": 0, "bad_fat": 4, "salt": 0.5, "is_liquid": False, "ml": None}
    bot.ai.calculate_nutrition = fake_calc

    m9 = M(uid4, photo=True); await bot._handle_photo(m9, uid4)
    check("составное: сначала название", "Вижу: Суп, салат и мясо" in m9.sent[-1], m9.sent[-1])
    m10 = M(uid4, "да"); await bot._handle_message_locked(m10)
    check("составное: «да» → вопрос про первый компонент", "суп" in m10.sent[-1].lower() and "грамм" in m10.sent[-1].lower(), m10.sent[-1])
    last = None
    for ans in ("300", "150", "100"):
        last = M(uid4, ans); await bot._handle_message_locked(last)
    saved4 = last.sent[-1]
    check("составное: сумма всех компонентов", "350" in saved4, saved4)
    check("составное: в названии все три", "суп" in saved4 and "салат" in saved4 and "мясо" in saved4, saved4)

    # 9. суп назван «кружкой» — бот поправляет на миску и не спрашивает «что пил?»
    uid6 = 9105; make_user(uid6)
    bot.ai.analyze_photo = lambda path: {"is_food": True, "is_compound": True, "is_drink": False,
                                         "confident": True,
                                         "name": "Тыквенный суп, салат и язык",
                                         "description": "Кружка с тыквенным супом-пюре; миска с салатом; тарелка с языком"}
    m12 = M(uid6, photo=True); await bot._handle_photo(m12, uid6)
    pend = bot._pending_clarification.get(uid6, {})
    check("суп в «кружке» → миска", "Кружка" not in pend.get("original_text", ""), pend.get("original_text"))
    m13 = M(uid6, "нет"); await bot._handle_message_locked(m13)
    check("еда + «нет»: «съел или выпил»", "съел или выпил" in m13.sent[-1], m13.sent[-1])
    check("еда + «нет»: без «пил»", "пил" not in m13.sent[-1].lower().replace("выпил", ""), m13.sent[-1])

    # 10. «похоже на» в описании больше не превращается в «вижу кружку»
    uid5 = 9104; make_user(uid5)
    bot.ai.analyze_photo = lambda path: {"is_food": True, "is_compound": True, "is_drink": False,
                                         "confident": True,
                                         "description": "Тарелка с супом-пюре, миска с салатом, тарелка с мясом (похоже на язык)"}
    m11 = M(uid5, photo=True); await bot._handle_photo(m11, uid5)
    check("«похоже на» не даёт вопрос про кружку", "кружк" not in m11.sent[-1].lower() and "пил" not in m11.sent[-1].lower(), m11.sent[-1])

    bad = [n for n, c in ok if not c]
    print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
    for n in bad: print("  ✗", n)

asyncio.run(main())
