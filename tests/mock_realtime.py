"""Мок Yandex Realtime API для проверки моста без реального ключа.

Повторяет события из официальных примеров Яндекса и проигрывает сценарий:
приветствие -> «хочу записаться на завтра» -> get_available_slots -> book_appointment -> end_conversation.
Запуск: python tests/mock_realtime.py  (слушает ws://127.0.0.1:8765/v1/realtime)
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import struct
import sys
from datetime import date, timedelta

from aiohttp import WSMsgType, web

RATE = 44100
LOG = []


def tone(sec: float = 0.4, freq: float = 440) -> str:
    n = int(RATE * sec)
    data = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / RATE))) for i in range(n))
    return base64.b64encode(data).decode()


async def say(ws, text: str):
    await ws.send_json({"type": "response.created", "response": {"id": "r"}})
    for w in text.split(" "):
        await ws.send_json({"type": "response.output_text.delta", "delta": w + " "})
    await ws.send_json({"type": "response.output_item.added", "item": {"type": "message", "id": "item_" + str(abs(hash(text)) % 1000)}})
    await ws.send_json({"type": "response.output_audio.delta", "item_id": "item_" + str(abs(hash(text)) % 1000), "delta": tone(3.0 if "Здравствуйте" in text else 0.4)})
    await ws.send_json({"type": "response.done"})


async def call(ws, name: str, args: dict, cid: str):
    await ws.send_json({"type": "response.created", "response": {"id": "r"}})
    await ws.send_json({"type": "response.output_item.done",
                        "item": {"type": "function_call", "name": name, "call_id": cid,
                                 "arguments": json.dumps(args, ensure_ascii=False)}})
    await ws.send_json({"type": "response.done"})


async def handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    LOG.append({"auth": request.headers.get("Authorization"), "query": request.query_string})
    await ws.send_json({"type": "session.created", "session": {"id": "mock-session"}})
    audio_bytes = 0
    stage = "greet"
    last_output = None
    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            continue
        ev = json.loads(msg.data)
        t = ev["type"]
        if t != "input_audio_buffer.append":
            LOG.append(ev)
            print("<<", t, file=sys.stderr)
        if t == "session.update":
            await ws.send_json({"type": "session.updated", "session": ev["session"]})
        elif t == "input_audio_buffer.append":
            audio_bytes += len(base64.b64decode(ev["audio"]))
            if stage == "wait_user" and audio_bytes > RATE * 2 * 1.5:  # 1.5 c речи
                stage = "slots"
                await ws.send_json({"type": "input_audio_buffer.speech_started"})
                await ws.send_json({"type": "input_audio_buffer.speech_stopped"})
                await ws.send_json({"type": "conversation.item.input_audio_transcription.completed",
                                    "transcript": "Хочу записаться на консультацию на завтра"})
                tomorrow = date.today() + timedelta(days=1)
                await call(ws, "get_available_slots", {"date": tomorrow.isoformat()}, "c1")
        elif t == "conversation.item.create":
            last_output = json.loads(ev["item"]["output"])
        elif t == "response.create":
            if stage == "greet":
                stage = "wait_user"
                await say(ws, "Здравствуйте! Я Даша, ассистент. Чем помочь?")
            elif stage == "slots":
                stage = "book"
                slot = last_output["slots"][0]["slot_id"]
                await call(ws, "book_appointment", {"slot_id": slot, "client_name": "Иван",
                                                    "phone": "8 916 123 45 67", "service": "Поверка манометров"}, "c2")
            elif stage == "book":
                stage = "end"
                await say(ws, f"Готово, номер записи {last_output.get('booking_number')}.")
                await call(ws, "end_conversation", {"summary": "Записан на поверку манометров"}, "c3")
            elif stage == "end":
                stage = "done"
                await say(ws, "До свидания!")
    with open(__import__("os").environ.get("MOCK_LOG", "mock_log.json"), "w") as f:
        json.dump(LOG, f, ensure_ascii=False, indent=1)
    return ws


app = web.Application()
app.router.add_get("/v1/realtime", handler)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=8765)
