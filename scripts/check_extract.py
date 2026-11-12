"""Проверка: работает ли текстовая модель, которая достаёт имя/телефон/тему из разговора.
Запуск из папки проекта:  .venv\\Scripts\\python.exe scripts\\check_extract.py   (на Маке: python scripts/check_extract.py)
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from app import extract  # noqa: E402

DIALOG = [
    {"role": "agent", "text": "Здравствуйте, это АУМСОФТ, меня зовут Ирина. Чем могу помочь?"},
    {"role": "user", "text": "добрый день это фёдор иванов беспокоит манометры надо проверить запишите на завтра на три "
                             "номер восемь восемьсот двенадцать раз два три четыре пять шесть семь"},
]
res = asyncio.run(extract.extract(DIALOG))
print("РЕЗУЛЬТАТ:", res or "модель не ответила — причина в строке WARNING выше; запись будет работать на разборе по словам")
