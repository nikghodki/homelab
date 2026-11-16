"""The gateway as an MCP server (streamable HTTP, JSON answers), so another engine (HolmesGPT in the A1 bake-off)
uses exactly the same tools, limits, redaction and replay clock as our own loop."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .gateway import TOOL_SPECS, Gateway, ToolContext


def app(gw: Gateway, ctx: ToolContext, token: str, counter: dict) -> FastAPI:
    api = FastAPI()

    @api.post("/mcp")
    async def mcp(req: Request) -> Response:
        if req.headers.get("authorization") != f"Bearer {token}":
            return Response(status_code=401)
        msg: dict[str, Any] = await req.json()
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:  # notification
            return Response(status_code=202)
        if method == "initialize":
            res = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                   "capabilities": {"tools": {}}, "serverInfo": {"name": "ops-tools", "version": "0.1"}}
        elif method == "tools/list":
            res = {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["parameters"],
                              "annotations": {"readOnlyHint": True}} for t in TOOL_SPECS]}
        elif method == "tools/call":
            p = msg.get("params", {})
            counter["calls"] = counter.get("calls", 0) + 1
            if counter["calls"] > counter.get("max", 25):
                res = {"content": [{"type": "text", "text": "tool budget used up; give your final answer now"}],
                       "isError": True}
            else:
                ref, text, ok = await gw.call(ctx, p.get("name", ""), p.get("arguments") or {})
                counter.setdefault("refs", []).append(ref)
                res = {"content": [{"type": "text", "text": text}], "isError": not ok}
        elif method == "ping":
            res = {}
        else:
            return JSONResponse({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}})
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": res})

    return api
