"""HTTP/WS сервер демо голосового ассистента."""
from __future__ import annotations

import asyncio
import logging
import re

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import booking, config, notify
from .mcp import router as mcp_router
from .realtime import Bridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

MAX_CONCURRENT = 10
_active = asyncio.Semaphore(MAX_CONCURRENT)

app = FastAPI(title="Voice booking demo")
STATIC = config.BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(mcp_router)


@app.on_event("startup")
def _startup() -> None:
    booking.init_db()
    if not (config.YANDEX_API_KEY and config.YANDEX_FOLDER_ID):
        log.warning("YANDEX_API_KEY / YANDEX_FOLDER_ID не заданы — заполните .env")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(STATIC / "admin.html")


@app.get("/api/config")
def api_config() -> dict:
    return {"company": config.COMPANY_NAME, "rate": config.AUDIO_OUT_RATE, "in_rate": config.AUDIO_IN_RATE, "email_enabled": notify.smtp_enabled(),
            "mic_gate": config.MIC_GATE}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "yandex_configured": bool(config.YANDEX_API_KEY and config.YANDEX_FOLDER_ID)}


def _check_admin(token: str | None) -> None:
    if config.ADMIN_TOKEN and token != config.ADMIN_TOKEN:
        raise HTTPException(401, "Нужен ?token=")


@app.get("/api/admin/data")
def admin_data(token: str | None = Query(default=None)) -> dict:
    _check_admin(token)
    return booking.list_all()


@app.get("/api/admin/calendar")
def admin_calendar(token: str | None = Query(default=None)) -> dict:
    _check_admin(token)
    return {"days": booking.calendar()}


@app.get("/api/slots")
def slots(date: str | None = None) -> dict:
    return booking.available_slots(date)


@app.get("/api/bookings/{number}.ics")
def booking_ics(number: str) -> Response:
    b = booking.get_booking(number)
    if not b:
        raise HTTPException(404)
    return Response(booking.to_ics(b), media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="{b["number"]}.ics"'})


class EmailReq(BaseModel):
    email: str


@app.post("/api/bookings/{number}/email")
async def booking_email(number: str, req: EmailReq) -> JSONResponse:
    b = booking.get_booking(number)
    if not b:
        raise HTTPException(404, "Запись не найдена")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", req.email.strip()):
        raise HTTPException(400, "Некорректный email")
    if not notify.smtp_enabled():
        raise HTTPException(503, "Отправка почты не настроена (SMTP_* в .env)")
    try:
        await notify.send_confirmation_email(req.email.strip(), b)
    except Exception as e:  # noqa: BLE001
        log.exception("email")
        raise HTTPException(502, f"Не удалось отправить письмо: {e}") from e
    return JSONResponse({"ok": True})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    if _active.locked():
        await ws.send_json({"type": "error", "message": "Все линии заняты, попробуйте через минуту"})
        await ws.close()
        return
    async with _active:
        bridge = Bridge(ws)
        await bridge.run()
    try:
        await ws.close()
    except Exception:  # noqa: BLE001
        pass
