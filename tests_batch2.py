"""Проверки пакета 2: FIX-02 (system-префикс), FIX-03 (сжатие), FIX-04 (справочная порция)."""
import os, io
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

from PIL import Image
import ai

ok = []
def check(name, cond, detail=""):
    ok.append((name, cond))
    print(("PASS  " if cond else "FAIL  ") + name + ((" | " + str(detail)) if detail else ""))


# ---------- фейковый клиент: перехватываем, что реально уходит в API ----------
class FakeMessage:
    def __init__(self, content): self.content = content
class FakeChoice:
    def __init__(self, content): self.message = FakeMessage(content)
class FakeResponse:
    def __init__(self, content): self.choices = [FakeChoice(content)]
class FakeCompletions:
    def __init__(self): self.calls = []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse('{"dish": "борщ", "questions": []}')
class FakeChat:
    def __init__(self): self.completions = FakeCompletions()
class FakeClient:
    def __init__(self): self.chat = FakeChat()
    @property
    def calls(self): return self.chat.completions.calls

real_client = ai.client
fake = FakeClient()
ai.client = fake

# FIX-02: одинаковый system-префикс во всех вызовах
ai.get_questions_for_ai("борщ 300")
ai.calculate_nutrition("борщ", "300 г")
first, second = fake.calls[0], fake.calls[1]
check("FIX-02: первым идёт system-сообщение",
      first["messages"][0]["role"] == "system" and second["messages"][0]["role"] == "system")
check("FIX-02: префикс одинаковый (кэш сработает)",
      first["messages"][0]["content"] == second["messages"][0]["content"] == ai.SYSTEM_BASE)
check("FIX-02: правила таска остались в user-сообщении",
      "Отвечай СТРОГО в формате JSON" in second["messages"][1]["content"])

# FIX-04: справочная порция попадает в промпт
fake.calls.clear()
ai.calculate_nutrition("борщ", "стандарт")
prompt = fake.calls[0]["messages"][1]["content"]
check("FIX-04: при «стандарт» подставляется порция из справочника",
      "Справочная порция" in prompt and "300" in prompt, prompt.split("\n\n")[1][:90])

fake.calls.clear()
ai.calculate_nutrition("борщ", "400 г")
check("FIX-04: без «стандарт» справочник не мешает",
      "Справочная порция" not in fake.calls[0]["messages"][1]["content"])

ai.client = real_client

# ---------- FIX-03: сжатие ----------
big = "/tmp/big_test.jpg"
Image.new("RGB", (3000, 2000), (120, 60, 40)).save(big, "JPEG", quality=95)
before = os.path.getsize(big)
path, mime, temp = ai._shrink_image(big)
after = os.path.getsize(path)
with Image.open(path) as im:
    w, h = im.size
check("FIX-03: большое фото уменьшено до 1280 px", max(w, h) <= 1280, f"{w}x{h}")
check("FIX-03: файл стал легче", after < before, f"{before//1024} КБ → {after//1024} КБ")
check("FIX-03: временный файл помечен для удаления", temp is True)
if temp:
    os.remove(path)

# маленькое фото не трогаем
small = "/tmp/small_test.jpg"
Image.new("RGB", (600, 400), (10, 10, 10)).save(small, "JPEG", quality=85)
path2, mime2, temp2 = ai._shrink_image(small)
check("FIX-03: маленькое фото не пережимается", temp2 is False and path2 == small)

# analyze_photo с фейковым клиентом: system + vision-модель + разбор ответа
ai.client = FakeClient()
ai.client.chat.completions.create = lambda **kw: (
    ai.client.chat.completions.calls.append(kw) or
    FakeResponse("еда: да\nсоставное: нет\nописание: Тарелка с борщом")
)
res = ai.analyze_photo(big)
call = ai.client.chat.completions.calls[-1]
check("FIX-03: картинка уходит в модель зрения", call["model"] == ai.VISION_MODEL, call["model"])
check("FIX-03: у фото тоже есть system-префикс", call["messages"][0]["role"] == "system")
check("FIX-03: ответ по фото разобран", res["is_food"] is True and "борщ" in res["description"].lower(), res)
ai.client = real_client

bad = [n for n, c in ok if not c]
print(f"\nИтог: {len(ok)} проверок, провалено {len(bad)}")
for n in bad:
    print("  ✗", n)
