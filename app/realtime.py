"""Мост: браузер <-> наш сервер <-> Yandex Realtime API.

Браузер шлёт сырые PCM16 (бинарные фреймы) и получает:
  - бинарные фреймы PCM16 с голосом агента;
  - JSON-события для интерфейса (транскрипт, статус, карточка записи).
Ключ API никогда не попадает в браузер — соединение с Яндексом держит сервер.
Функции (запись, слоты) тоже выполняются на сервере.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

import aiohttp
from fastapi import WebSocket, WebSocketDisconnect

from . import agent, booking, config

log = logging.getLogger("realtime")

MAX_SESSION_SEC = 360  # 6 минут: на запись хватает, защищает от «забытых» вкладок и лишних расходов


class Bridge:
    def __init__(self, browser: WebSocket):
        self.browser = browser
        self.yws: aiohttp.ClientWebSocketResponse | None = None
        self.session_id = ""
        self.started_at = booking.now().isoformat(timespec="seconds")
        self.transcript: list[dict] = []
        self.ctx: dict = {}
        # «эпохи» нужны, чтобы после перебивания не доигрывать хвост старого ответа
        self.epoch = 0
        self.response_epoch: int | None = None
        self.agent_text = ""
        self.text_source: str | None = None
        self.greeted = False
        self.closed = False
        self.speaking = False
        self.resp_had_call = False
        # для перебивания: id текущего аудио-ответа и ожидающий truncate
        self.cur_item_id: str | None = None
        self.pending_truncate: str | None = None
        self.last_audio_item: str | None = None

    # ---------- отправка в браузер ----------

    async def ui(self, event: dict) -> None:
        if self.closed:
            return
        try:
            await self.browser.send_text(json.dumps(event, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            self.closed = True

    async def ui_audio(self, pcm: bytes) -> None:
        if self.closed:
            return
        try:
            await self.browser.send_bytes(pcm)
        except Exception:  # noqa: BLE001
            self.closed = True

    # ---------- отправка в Яндекс ----------

    async def y(self, event: dict) -> None:
        if self.yws is not None and not self.yws.closed:
            await self.yws.send_str(json.dumps(event, ensure_ascii=False))

    async def setup_session(self) -> None:
        output: dict = {"format": {"type": "audio/pcm", "rate": config.AUDIO_OUT_RATE}}
        if config.VOICE:
            output["voice"] = config.VOICE
        if config.VOICE_ROLE:
            output["role"] = config.VOICE_ROLE
        session: dict = {
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": config.AUDIO_IN_RATE},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": config.VAD_THRESHOLD,
                        "silence_duration_ms": config.VAD_SILENCE_MS,
                    },
                },
                "output": output,
            },
            "tools": agent.tool_schemas(),
        }
        if config.LANGUAGE:
            session["audio"]["input"]["languages"] = [config.LANGUAGE]
        if config.AGENT_PROMPT_ID:
            # голос и настройки речи — из агента AI Studio; промпт и функции — наши
            session["prompt"] = {"id": config.AGENT_PROMPT_ID}
        session["instructions"] = agent.build_instructions()
        await self.y({"type": "session.update", "session": session})

    async def greet(self) -> None:
        if self.greeted or not config.AGENT_SPEAKS_FIRST:
            return
        self.greeted = True
        await self.y({"type": "response.create"})

    # ---------- основной цикл ----------

    async def run(self) -> None:
        if not (config.YANDEX_API_KEY and config.YANDEX_FOLDER_ID) and "localhost" not in config.REALTIME_URL \
                and "127.0.0.1" not in config.REALTIME_URL:
            await self.ui({"type": "error", "message": "На сервере не заданы YANDEX_API_KEY и YANDEX_FOLDER_ID (.env)"})
            return

        headers = {"Authorization": f"Api-Key {config.YANDEX_API_KEY}"}
        try:
            async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10)) as http:
                async with http.ws_connect(config.REALTIME_URL, headers=headers, heartbeat=20.0,
                                           max_msg_size=0) as yws:
                    self.yws = yws
                    await self.setup_session()
                    await self.ui({"type": "status", "state": "connected"})
                    asyncio.get_running_loop().call_later(2.5, lambda: asyncio.ensure_future(self.greet()))
                    tasks = [
                        asyncio.create_task(self.uplink()),
                        asyncio.create_task(self.downlink()),
                    ]
                    try:
                        await asyncio.wait_for(
                            asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED), MAX_SESSION_SEC)
                    except asyncio.TimeoutError:
                        await self.ui({"type": "error", "message": "Время сессии истекло"})
                    for t in tasks:
                        t.cancel()
        except aiohttp.WSServerHandshakeError as e:
            log.error("handshake error: %s %s", e.status, e.message)
            await self.ui({"type": "error", "message": f"Yandex Realtime отклонил подключение ({e.status}). Проверьте ключ, каталог и роли."})
        except asyncio.TimeoutError:
            log.error("yandex connect timeout")
            await self.ui({"type": "error", "message": "Yandex Realtime не ответил за 10 секунд. Попробуйте ещё раз."})
        except aiohttp.ClientError as e:
            log.error("connection error: %s", e)
            await self.ui({"type": "error", "message": f"Нет соединения с Yandex Realtime: {e}"})
        finally:
            self.closed = True
            if self.transcript:
                try:
                    booking.save_conversation(self.session_id, self.started_at, self.transcript,
                                              self.ctx.get("summary", ""))
                except Exception as e:  # noqa: BLE001
                    log.warning("save conversation: %s", e)

    async def uplink(self) -> None:
        """Браузер -> Яндекс."""
        try:
            while True:
                msg = await self.browser.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
                if msg.get("bytes"):
                    await self.y({"type": "input_audio_buffer.append",
                                  "audio": base64.b64encode(msg["bytes"]).decode("ascii")})
                elif msg.get("text"):
                    data = json.loads(msg["text"])
                    if data.get("type") == "stop":
                        return
                    if data.get("type") == "played":
                        await self.truncate(data)
                    elif data.get("type") == "barge":
                        await self.barge(data)
        except (WebSocketDisconnect, RuntimeError):
            return

    async def truncate(self, data: dict) -> None:
        """Сообщаем модели, какую часть ответа клиент реально услышал (как в протоколе Realtime)."""
        item_id, self.pending_truncate = self.pending_truncate, None
        if not item_id or data.get("full"):
            return
        ms = max(0, int(data.get("ms") or 0))
        log.info("truncate %s at %d ms", item_id, ms)
        await self.y({"type": "conversation.item.truncate", "item_id": item_id,
                      "content_index": 0, "audio_end_ms": ms})

    async def barge(self, data: dict) -> None:
        """Клиент перебил ассистента (определил браузер): отменяем ответ и обрезаем непрозвучавшее."""
        self.epoch += 1
        self.response_epoch = None
        self.speaking = False
        if self.agent_text:
            self._finish_agent_text(interrupted=True)
        item, self.last_audio_item, self.pending_truncate = self.last_audio_item, None, None
        log.info("barge-in at %s ms (item %s)", data.get("ms"), item)
        await self.y({"type": "response.cancel"})
        if item and not data.get("full"):
            await self.y({"type": "conversation.item.truncate", "item_id": item, "content_index": 0,
                          "audio_end_ms": max(0, int(data.get("ms") or 0))})

    def _finish_agent_text(self, interrupted: bool = False) -> None:
        text = self.agent_text.strip()
        if text:
            self.ctx["last_agent"] = (text, self.ctx.get("user_turns", 0))
            self.transcript.append({"role": "agent", "text": text + (" …" if interrupted else ""),
                                    "t": round(time.time())})
        self.agent_text = ""
        self.text_source = None

    async def downlink(self) -> None:
        """Яндекс -> браузер (+ выполнение функций)."""
        assert self.yws is not None
        async for msg in self.yws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            ev = json.loads(msg.data)
            et = ev.get("type", "")
            if config.DEBUG_EVENTS and et not in ("response.output_audio.delta", "response.output_text.delta",
                                                  "response.output_audio_transcript.delta"):
                brief = {k: v for k, v in ev.items() if k in ("item_id", "transcript", "audio_start_ms",
                                                             "audio_end_ms", "response_id", "error")}
                if et == "response.output_item.done":
                    it = ev.get("item") or {}
                    brief = {"item_type": it.get("type"), "name": it.get("name"), "id": it.get("id")}
                log.info("EV %s %s", et, json.dumps(brief, ensure_ascii=False)[:300])

            if et == "session.created":
                self.session_id = (ev.get("session") or {}).get("id", "")
                log.info("session %s", self.session_id)

            elif et == "session.updated":
                sess = ev.get("session") or {}
                out = (sess.get("audio") or {}).get("output") or {}
                tools = [t.get("name") for t in (sess.get("tools") or [])]
                log.info("session.updated: voice=%r role=%r tools=%s", out.get("voice"), out.get("role"), tools)
                await self.greet()

            elif et == "input_audio_buffer.speech_started":
                # пользователь заговорил — перебиваем агента
                self.epoch += 1
                self.response_epoch = None
                if self.agent_text:
                    self._finish_agent_text(interrupted=True)
                # если агент говорил — просим браузер сказать, сколько успело прозвучать, и обрежем ответ
                # (ответ мог уже сгенерироваться целиком, но ещё звучать в браузере — решает браузер)
                need = bool(self.last_audio_item)
                self.pending_truncate = self.last_audio_item
                self.last_audio_item = None
                self.speaking = False
                await self.ui({"type": "clear", "need_played": need})
                await self.ui({"type": "status", "state": "listening"})

            elif et == "input_audio_buffer.speech_stopped":
                self.ctx["user_turns"] = self.ctx.get("user_turns", 0) + 1
                await self.ui({"type": "status", "state": "thinking"})

            elif et == "conversation.item.input_audio_transcription.completed":
                text = (ev.get("transcript") or "").strip()
                if text:
                    self.ctx.setdefault("user_texts", []).append(text)
                    self.transcript.append({"role": "user", "text": text, "t": round(time.time())})
                    await self.ui({"type": "user_text", "text": text})

            elif et == "response.created":
                self.response_epoch = self.epoch
                self.resp_had_call = False
                self.cur_item_id = None
                await self.ui({"type": "agent_start"})

            elif et in ("response.output_text.delta", "response.output_audio_transcript.delta"):
                if self.response_epoch != self.epoch:
                    continue
                if self.text_source is None:
                    self.text_source = et
                if et != self.text_source:
                    continue  # не дублируем текст, если сервер шлёт оба вида событий
                delta = ev.get("delta", "")
                if delta:
                    self.agent_text += delta
                    await self.ui({"type": "agent_delta", "text": delta})

            elif et == "response.output_item.added":
                item = ev.get("item") or {}
                if item.get("type") == "message" and item.get("id"):
                    self.cur_item_id = item["id"]

            elif et == "response.output_audio.delta":
                if ev.get("item_id") and self.response_epoch == self.epoch:
                    self.cur_item_id = ev["item_id"]
                if self.response_epoch == self.epoch and ev.get("delta"):
                    if not self.speaking:
                        self.speaking = True
                        await self.ui({"type": "status", "state": "speaking"})
                    if self.cur_item_id:
                        self.last_audio_item = self.cur_item_id
                    await self.ui_audio(base64.b64decode(ev["delta"]))

            elif et == "response.output_item.done":
                item = ev.get("item") or {}
                if item.get("type") == "function_call":
                    await self.handle_function_call(item)

            elif et == "response.done":
                self.speaking = False
                self._finish_agent_text()
                await self.ui({"type": "agent_done"})
                # закрываем после ответа, который прозвучал ПОСЛЕ end_conversation
                if self.ctx.get("end_requested") and not self.resp_had_call:
                    await self.ui({"type": "end", "summary": self.ctx.get("summary", "")})

            elif et == "error":
                log.error("yandex error: %s", json.dumps(ev, ensure_ascii=False))
                err = ev.get("error") or {}
                msg_text = err.get("message") or str(ev)[:300]
                low = json.dumps(ev, ensure_ascii=False).lower()
                if "truncat" in low or "cancel" in low:
                    continue  # если сервер не поддерживает truncate — не пугаем клиента, только лог
                await self.ui({"type": "error", "message": msg_text})

        log.info("yandex ws closed")

    async def handle_function_call(self, item: dict) -> None:
        name = item.get("name", "")
        call_id = item.get("call_id")
        args = agent.parse_args(item.get("arguments"))
        log.info("tool %s %s", name, args)
        self.resp_had_call = True
        await self.ui({"type": "tool", "name": name})
        try:
            result = await agent.run_tool(name, args, self.ui, self.ctx)
        except Exception as e:  # noqa: BLE001
            log.exception("tool failed")
            result = {"ok": False, "error": f"Техническая ошибка: {e}. Извинись и предложи оставить заявку на звонок."}
        self.transcript.append({"role": "tool", "name": name, "args": args, "result": result})
        await self.y({
            "type": "conversation.item.create",
            "item": {"type": "function_call_output", "call_id": call_id,
                     "output": json.dumps(result, ensure_ascii=False)},
        })
        # после результата функции просим модель продолжить (как в примерах Яндекса)
        await self.y({"type": "response.create"})
