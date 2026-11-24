import os, asyncio, time
os.environ["BOT_TOKEN"]="123456:TEST"; os.environ["DEEPSEEK_API_KEY"]="sk-test"
import ai, bot

print("модель для текста :", ai.TEXT_MODEL)
print("модель для фото   :", ai.VISION_MODEL)

# «не знаю» теперь даёт реальный вес из справочника
for d in ("борщ", "яблоко", "пиво", "непонятное"):
    print(f"  не знаю / {d}: {ai.standard_portion(d)}")

# числа от ИИ приводятся к числам
print("coerce:", ai._coerce_nutrition({"calories":"450 ккал","protein":"~15 г","fat":"20","carbs":45,"weight":"300 г","sugar":"","bad_fat":0,"salt":"1,5","is_liquid":"false","ml":"250 мл"}))

# цикл событий не блокируется, пока думает модель
async def main():
    ticks = 0
    async def counter():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)
    task = asyncio.create_task(counter())
    t0 = time.perf_counter()
    await bot._ai(time.sleep, 1.0)          # имитация запроса к ИИ
    dt = time.perf_counter() - t0
    task.cancel()
    print(f"пока ИИ «думал» {dt:.2f} c, бот успел обработать {ticks} циклов (0 = был заморожен)")

asyncio.run(main())
print("Dispatcher:", type(bot.dp).__name__, "| пул обработчиков собран")
