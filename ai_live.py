import os, time, json, urllib.request, urllib.parse
import ai

def t(fn, *a):
    t0=time.time()
    try: r=fn(*a)
    except Exception as e: r=f"ИСКЛЮЧЕНИЕ: {e}"
    return r, round(time.time()-t0,1)

print("ТЕКСТОВАЯ МОДЕЛЬ:", ai.TEXT_MODEL, "| ФОТО:", ai.VISION_MODEL)

r, dt = t(ai.get_questions_for_ai, "борщ 300")
print(f"\n1) «борщ 300» -> {dt}s\n   {r}")

r, dt = t(ai.get_questions_for_ai, "съел суп")
print(f"\n2) «съел суп» -> {dt}s\n   {r}")

r, dt = t(ai.split_components, "пюре с котлетой и салат из огурцов")
print(f"\n3) составное блюдо -> {dt}s\n   {r}")

r, dt = t(ai.calculate_nutrition, "борщ", "300 г")
print(f"\n4) КБЖУ борща 300 г -> {dt}s\n   {r}")

r, dt = t(ai.calculate_nutrition, "пиво", "0,5 л светлое")
print(f"\n5) пиво 0,5 л -> {dt}s\n   {r}")

r, dt = t(ai.ask_ai_question, "можно ли есть после шести?")
print(f"\n6) вопрос-ответ -> {dt}s\n   {str(r)[:300]}")

r, dt = t(ai.generate_day_summary, {"week":1}, {"calories":1850,"protein":70,"fat":65,"carbs":190,"sugar":30,"bad_fat":10,"salt":6}, 1600)
print(f"\n7) итог дня -> {dt}s\n   {str(r)[:300]}")
