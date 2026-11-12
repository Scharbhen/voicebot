"""Извлечение имени, телефона и темы из разговора текстовой моделью Яндекса.

Вызывается в момент записи: модель читает весь диалог и возвращает JSON. Если модель недоступна
(нет прав у ключа, сеть, таймаут) — возвращается {}, и запись работает на запасном разборе по словам.
"""
from __future__ import annotations

import json
import logging
import re

import aiohttp

from . import config

log = logging.getLogger("extract")

SYSTEM = """Ты извлекаешь данные клиента из расшифровки телефонного разговора с администратором.
Верни ТОЛЬКО JSON без пояснений: {"name": "...", "phone": "...", "topic": "..."}
- name: имя (и фамилия, если назвал) клиента, как он сам представился, в именительном падеже с заглавной буквы.
  Берётся из слов клиента в любой форме: «меня зовут…», «это Фёдор», «Иванов беспокоит», ответ на вопрос об имени.
- phone: номер телефона клиента только цифрами, как он его продиктовал (слова «раз» = 1). Если клиент исправлял
  номер — последний вариант. Ничего не дописывай и не угадывай недостающие цифры.
- topic: по какому вопросу клиент обращается, коротко (2–5 слов), например «поверка манометров».
  «Проверка» приборов означает «поверка».
Чего клиент не говорил — пустая строка. Расшифровка может содержать повторы и обрывки одной фразы — это нормально."""


async def extract(transcript: list[dict]) -> dict:
    if not (config.EXTRACT_MODEL and config.YANDEX_API_KEY and config.YANDEX_FOLDER_ID):
        return {}
    lines = [("Клиент: " if m["role"] == "user" else "Администратор: ") + m["text"]
             for m in transcript if m.get("role") in ("user", "agent") and m.get("text")]
    if not lines:
        return {}
    body = {
        "model": f"gpt://{config.YANDEX_FOLDER_ID}/{config.EXTRACT_MODEL}",
        "temperature": 0,
        "max_tokens": 200,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": "\n".join(lines[-30:])}],
    }
    headers = {"Authorization": f"Bearer {config.YANDEX_API_KEY}", "OpenAI-Project": config.YANDEX_FOLDER_ID}
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=4)) as s:
            async with s.post(config.EXTRACT_URL, json=body, headers=headers) as r:
                raw = await r.text()
                if r.status != 200:
                    log.warning("extract: HTTP %s %s", r.status, raw[:300])
                    return {}
        content = json.loads(raw)["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        data = json.loads(m.group(0)) if m else {}
        out = {k: str(data.get(k) or "").strip() for k in ("name", "phone", "topic")}
        log.info("extract: %s", json.dumps(out, ensure_ascii=False))
        return {k: v for k, v in out.items() if v}
    except Exception as e:  # noqa: BLE001
        log.warning("extract failed: %r", e)
        return {}
