"""A minimal MCP client for the streamable-HTTP transport (JSON-RPC 2.0 over POST; JSON or SSE answers).

Small on purpose: the agent only needs initialize, tools/list and tools/call against three pinned servers, and the
SDKs' APIs move fast. Every call has a timeout; a broken session is re-initialised once.
"""
from __future__ import annotations

import itertools
import json
from typing import Any

import httpx

PROTOCOL = "2025-06-18"


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, url: str, token: str = "", timeout: float = 60.0, name: str = "mcp"):
        self.url, self.name = url, name
        self.headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = "Bearer " + token
        self.http = httpx.AsyncClient(timeout=timeout)
        self.session: str | None = None
        self.ids = itertools.count(1)
        self._tools: list[dict] | None = None

    async def close(self) -> None:
        await self.http.aclose()

    @staticmethod
    def _parse(resp: httpx.Response, want_id: int) -> dict:
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for block in resp.text.split("\n\n"):
                data = "\n".join(l[5:].lstrip() for l in block.splitlines() if l.startswith("data:"))
                if not data:
                    continue
                msg = json.loads(data)
                if msg.get("id") == want_id:
                    return msg
            raise MCPError("no response in event stream")
        return resp.json()

    async def _rpc(self, method: str, params: dict | None = None, notify: bool = False) -> Any:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        rid = 0
        if not notify:
            rid = next(self.ids)
            body["id"] = rid
        h = dict(self.headers)
        if self.session:
            h["Mcp-Session-Id"] = self.session
            h["MCP-Protocol-Version"] = PROTOCOL
        r = await self.http.post(self.url, headers=h, json=body)
        if "mcp-session-id" in r.headers:
            self.session = r.headers["mcp-session-id"]
        if notify:
            return None
        if r.status_code >= 400:
            raise MCPError(f"{self.name} {method}: HTTP {r.status_code} {r.text[:200]}")
        msg = self._parse(r, rid)
        if "error" in msg:
            raise MCPError(f"{self.name} {method}: {msg['error'].get('message')}")
        return msg.get("result")

    async def connect(self) -> None:
        await self._rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                       "clientInfo": {"name": "ops-agent", "version": "0.1"}})
        await self._rpc("notifications/initialized", notify=True)

    async def _ensure(self) -> None:
        if self.session is None:
            await self.connect()

    async def tools(self) -> list[dict]:
        await self._ensure()
        if self._tools is None:
            out, cursor = [], None
            while True:
                res = await self._rpc("tools/list", {"cursor": cursor} if cursor else {})
                out += res.get("tools", [])
                cursor = res.get("nextCursor")
                if not cursor:
                    break
            self._tools = out
        return self._tools

    async def call(self, tool: str, args: dict) -> tuple[bool, str]:
        """Returns (ok, text). Tool errors come back as ok=False with the server's message."""
        for attempt in (1, 2):
            try:
                await self._ensure()
                res = await self._rpc("tools/call", {"name": tool, "arguments": args})
                break
            except (httpx.HTTPError, MCPError) as e:
                if attempt == 2:
                    return False, f"{self.name}.{tool} failed: {e}"
                self.session = None
        parts = []
        for c in res.get("content", []):
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            else:
                parts.append(f"[{c.get('type')} content omitted]")
        if not parts and res.get("structuredContent") is not None:
            parts.append(json.dumps(res["structuredContent"]))
        return (not res.get("isError", False)), "\n".join(parts)
