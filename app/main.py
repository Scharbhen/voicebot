"""HTTP/WS сервер демо голосового ассистента."""
from __future__ import annotations

import asyncio
import hmac
import logging
import re
import time
from collections import deque

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
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


# ---------- доступ к виджету по ключу ----------
KEY_COOKIE = "vb_key"
OPEN_PREFIXES = ("/admin", "/api/admin", "/api/health", "/static", "/mcp")
DENIED_HTML = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Доступ по ссылке</title><body style="font-family:system-ui;padding:40px;max-width:520px;margin:auto">
<h2>Демо доступно по персональной ссылке</h2><p>Попросите ссылку у менеджера.</p></body>"""


def _key_ok(given: str | None) -> bool:
    return bool(given) and hmac.compare_digest(given, config.ACCESS_KEY)


@app.middleware("http")
async def access_key(request: Request, call_next):
    if not config.ACCESS_KEY or request.url.path.startswith(OPEN_PREFIXES):
        return await call_next(request)
    from_query = request.query_params.get("key")
    if not (_key_ok(request.cookies.get(KEY_COOKIE)) or _key_ok(from_query)):
        if request.url.path == "/":
            return HTMLResponse(DENIED_HTML, status_code=403)
        return JSONResponse({"detail": "Нужна ссылка с ключом доступа"}, status_code=403)
    resp = await call_next(request)
    if _key_ok(from_query):  # запоминаем ключ — дальше ссылка работает без него
        resp.set_cookie(KEY_COOKIE, from_query, max_age=30 * 86400, httponly=True, secure=True, samesite="lax")
    return resp


# ---------- лимит разговоров ----------
_starts: deque[float] = deque()
_starts_ip: dict[str, deque[float]] = {}


def _client_ip(ws: WebSocket) -> str:
    fwd = ws.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (ws.client.host if ws.client else "?")


def _rate_limited(ip: str) -> str | None:
    now = time.time()
    for q in (_starts, *_starts_ip.values()):
        while q and q[0] < now - 3600:
            q.popleft()
    for k in [k for k, q in _starts_ip.items() if not q]:
        del _starts_ip[k]
    q_ip = _starts_ip.setdefault(ip, deque())
    if config.MAX_SESSIONS_PER_HOUR and len(_starts) >= config.MAX_SESSIONS_PER_HOUR:
        return "Демо сейчас перегружено, попробуйте позже"
    if config.MAX_SESSIONS_PER_IP_HOUR and len(q_ip) >= config.MAX_SESSIONS_PER_IP_HOUR:
        return "Слишком много разговоров подряд, попробуйте через час"
    _starts.append(now)
    q_ip.append(now)
    return None


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
    if config.ACCESS_KEY and not (_key_ok(ws.cookies.get(KEY_COOKIE)) or _key_ok(ws.query_params.get("key"))):
        await ws.send_json({"type": "error", "message": "Нужна ссылка с ключом доступа"})
        await ws.close()
        return
    limited = _rate_limited(_client_ip(ws))
    if limited:
        log.info("rate limit: %s", _client_ip(ws))
        await ws.send_json({"type": "error", "message": limited})
        await ws.close()
        return
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
