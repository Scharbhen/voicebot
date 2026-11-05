"""Минимальный MCP-сервер (JSON-RPC поверх HTTP, без стриминга) с функциями записи.

Нужен, чтобы голосовой агент, созданный в интерфейсе Yandex AI Studio (и в будущем — телефонный канал через SIP),
пользовался тем же расписанием, что и веб-виджет. URL: POST /mcp, заголовок Authorization: Bearer <MCP_TOKEN>.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from . import agent, config

log = logging.getLogger("mcp")
router = APIRouter()

MCP_TOOLS = ["get_available_slots", "book_appointment", "cancel_appointment", "request_callback"]
PROTOCOL = "2025-03-26"


def _tools() -> list[dict]:
    out = []
    for t in agent.tool_schemas():
        if t["name"] in MCP_TOOLS:
            out.append({"name": t["name"], "description": t["description"], "inputSchema": t["parameters"]})
    return out


async def _noop(_: dict) -> None:
    return None


def _ok(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_, code, msg):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": msg}}


async def _handle(msg: dict) -> dict | None:
    method, id_ = msg.get("method"), msg.get("id")
    if id_ is None:  # уведомление (notifications/initialized и т.п.)
        return None
    if method == "initialize":
        return _ok(id_, {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
                         "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": {"name": f"{config.COMPANY_NAME} booking", "version": "1.0"}})
    if method == "ping":
        return _ok(id_, {})
    if method == "tools/list":
        return _ok(id_, {"tools": _tools()})
    if method == "tools/call":
        p = msg.get("params") or {}
        name = p.get("name")
        if name not in MCP_TOOLS:
            return _err(id_, -32602, f"Unknown tool {name}")
        result = await agent.run_tool(name, p.get("arguments") or {}, _noop, {"channel": "agent"})
        log.info("mcp %s -> %s", name, str(result)[:200])
        return _ok(id_, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                         "isError": not result.get("ok", True)})
    return _err(id_, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    if config.MCP_TOKEN and request.headers.get("authorization", "") != f"Bearer {config.MCP_TOKEN}":
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    if isinstance(body, list):
        res = [r for r in [await _handle(m) for m in body] if r is not None]
        return JSONResponse(res) if res else Response(status_code=202)
    res = await _handle(body)
    return JSONResponse(res) if res is not None else Response(status_code=202)


@router.get("/mcp")
async def mcp_get():
    # стриминг (SSE) не поддерживаем
    return Response(status_code=405)
