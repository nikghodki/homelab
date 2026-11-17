"""
title: TPS meter
author: homelab (cluster/apps/open-webui/functions/tps_meter.py)
version: 1.0.1
license: MIT
description: Live "≈ N tok/s" while a reply streams, then tok/s, output tokens, time to first token and total time.
"""

# Kept in Git and loaded by the open-webui-config Job (runbooks/open-webui.md, "Config from Git"); edits in the admin
# UI are overwritten by the next sync. Global filter: every model, Hermes included (there it measures the agent's
# whole run: every LLM call and tool step between the first and the last token).
#
# Counting: the provider's exact `usage.completion_tokens` from the final chunk when it sends one (Open WebUI asks for
# it with stream_options.include_usage when the model's "usage" capability is on); otherwise an estimate from the
# streamed text (about 4 characters a token, at least one per chunk), shown with "≈". Reasoning tokens count: they
# are output tokens and the providers' usage includes them.
#
# tok/s = output tokens / time from the first to the last token (generation speed; the wait before the first token
# is reported separately as TTFT, measured from the inlet, i.e. when Open WebUI starts handling the request).
# Live updates are throttled (each status is also saved in the chat): every `update_interval` s, then every
# `slow_update_interval` s after `slow_after_updates` updates.

from __future__ import annotations

import math
import time
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

CHARS_PER_TOKEN = 4.0
STALE_AFTER_S = 3600.0
MIN_RATE_SPAN_S = 0.25  # live tok/s only once tokens have streamed for this long  # meters for requests that never finished (client gone) are dropped after this


def chunk_text(chunk: dict) -> str:
    """Generated text in one OpenAI-style chunk: content, reasoning and tool-call arguments of every choice."""
    out = []
    for choice in chunk.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or choice.get("message") or {}
        if not isinstance(delta, dict):
            continue
        for key in ("content", "reasoning_content", "reasoning"):
            value = delta.get(key)
            if isinstance(value, str):
                out.append(value)
        for call in delta.get("tool_calls") or []:
            fn = call.get("function") if isinstance(call, dict) else None
            if isinstance(fn, dict):
                out.append(str(fn.get("name") or "") + str(fn.get("arguments") or ""))
    return "".join(out)


def chunk_usage(chunk: dict) -> Optional[int]:
    """Exact output tokens if this chunk carries a usage block (OpenAI or Responses naming), else None."""
    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        return None
    for key in ("completion_tokens", "output_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def chunk_finished(chunk: dict) -> bool:
    return any(isinstance(c, dict) and c.get("finish_reason") for c in chunk.get("choices") or [])


def estimate_tokens(text: str) -> int:
    """Tokens in one streamed piece of text: ~4 characters a token, at least one (a chunk is usually one token)."""
    return max(1, round(len(text) / CHARS_PER_TOKEN)) if text else 0


def fmt_seconds(s: float) -> str:
    if s < 10:
        return f"{s:.2f} s"
    if s < 60:
        return f"{s:.1f} s"
    m, sec = divmod(int(round(s)), 60)
    return f"{m} min {sec} s"


def fmt_rate(r: float) -> str:
    return f"{r:.1f}" if r < 100 else f"{r:.0f}"


class Meter:
    """Timing and token count of one streamed reply (pure logic; the clock is passed in)."""

    def __init__(self, t0: float, label: str = ""):
        self.t0 = t0
        self.label = label
        self.t_first: Optional[float] = None
        self.t_last: Optional[float] = None
        self.estimated = 0
        self.exact: Optional[int] = None
        self.finished = False
        self.reported = False
        self.last_emit: Optional[float] = None
        self.updates = 0

    def add(self, chunk: dict, now: float) -> None:
        text = chunk_text(chunk)
        if text:
            if self.t_first is None:
                self.t_first = now
            self.t_last = now
            self.estimated += estimate_tokens(text)
        usage = chunk_usage(chunk)
        if usage is not None:
            self.exact = usage
        if chunk_finished(chunk):
            self.finished = True

    @property
    def tokens(self) -> int:
        return self.exact if self.exact is not None else self.estimated

    def generation_time(self) -> float:
        if self.t_first is None or self.t_last is None:
            return 0.0
        return self.t_last - self.t_first

    def rate(self, now: Optional[float] = None) -> Optional[float]:
        """Tokens per second from the first token to the last one (or to `now` while streaming)."""
        if self.t_first is None:
            return None
        end = self.t_last if now is None else max(now, self.t_last or now)
        span = end - self.t_first
        tokens = self.tokens
        if span < 0.05:  # one burst: fall back to the time since the request started
            span = end - self.t0
        if span <= 0 or tokens <= 0:
            return None
        return tokens / span

    def live_due(self, now: float, interval: float, slow_after: int, slow_interval: float) -> bool:
        if self.t_first is None:
            return False
        step = interval if self.updates < slow_after else slow_interval
        return self.last_emit is None or now - self.last_emit >= step

    def live_text(self, now: float) -> str:
        if self.t_first is not None and now - self.t_first < MIN_RATE_SPAN_S:
            # too early for a rate (one token would read as "0.3 tok/s" after a slow start)
            return f"{self.label}first token after {fmt_seconds(self.t_first - self.t0)}"
        r = self.rate(now)
        speed = f"≈ {fmt_rate(r)} tok/s" if r is not None else "≈ … tok/s"
        return f"{self.label}{speed} · {self.estimated} tokens so far"

    def final_text(self, end: float) -> str:
        """The closing status; `end` is when the stream ended."""
        exact = self.exact is not None
        approx = "" if exact else "≈ "
        r = self.rate()
        parts = [f"{approx}{fmt_rate(r)} tok/s" if r is not None else "no tokens"]
        parts.append(f"{approx}{self.tokens} output tokens")
        if self.t_first is not None:
            parts.append(f"first token {fmt_seconds(self.t_first - self.t0)}")
        last = self.t_last if self.t_last is not None else end
        parts.append(f"{fmt_seconds(max(end, last) - self.t0)} total")
        return self.label + " · ".join(parts)


Emitter = Callable[[dict], Awaitable[Any]]


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=100, description="Run after other filters (higher runs later)")
        update_interval: float = Field(default=0.5, description="Seconds between live updates")
        slow_after_updates: int = Field(default=60, description="After this many live updates, slow down")
        slow_update_interval: float = Field(default=2.0, description="Seconds between live updates after that")
        pipeline_model_prefixes: str = Field(
            default="hermes.", description="Model ids starting with one of these (comma-separated) are agents"
        )
        pipeline_label: str = Field(default="Agent run: ", description="Prefix of the status for those models")

    def __init__(self):
        self.valves = self.Valves()
        self.meters: dict[str, Meter] = {}
        self.clock: Callable[[], float] = time.monotonic

    # --- helpers
    @staticmethod
    def _key(metadata: Optional[dict], request: Any = None) -> str:
        metadata = metadata or {}
        for key in ("message_id", "id"):
            if metadata.get(key):
                return f"{metadata.get('chat_id') or ''}:{metadata[key]}"
        return f"req:{id(request)}"

    def _label(self, model: Optional[dict]) -> str:
        model_id = (model or {}).get("id") or ""
        prefixes = [p.strip() for p in self.valves.pipeline_model_prefixes.split(",") if p.strip()]
        return self.valves.pipeline_label if any(model_id.startswith(p) for p in prefixes) else ""

    def _prune(self, now: float) -> None:
        for key in [k for k, m in self.meters.items() if now - m.t0 > STALE_AFTER_S]:
            del self.meters[key]

    @staticmethod
    async def _status(emitter: Optional[Emitter], text: str, done: bool) -> None:
        if emitter is None:
            return
        try:
            await emitter({"type": "status", "data": {"description": text, "done": done, "hidden": False}})
        except Exception:  # never break a chat because a status couldn't be sent
            pass

    async def _final(self, key: str, meter: Meter, emitter: Optional[Emitter], end: float) -> None:
        if meter.reported:
            return
        meter.reported = True
        self.meters.pop(key, None)
        if meter.t_first is None and meter.exact is None:
            return  # nothing was generated (error, cancelled): say nothing
        await self._status(emitter, meter.final_text(end), True)

    # --- Open WebUI hooks
    async def inlet(self, body: dict, __metadata__: Optional[dict] = None, __model__: Optional[dict] = None,
                    __request__: Any = None) -> dict:
        now = self.clock()
        self._prune(now)
        self.meters[self._key(__metadata__, __request__)] = Meter(now, self._label(__model__))
        return body

    async def stream(self, event: dict, __event_emitter__: Optional[Emitter] = None,
                     __metadata__: Optional[dict] = None, __model__: Optional[dict] = None,
                     __request__: Any = None) -> dict:
        if not isinstance(event, dict):
            return event
        now = self.clock()
        key = self._key(__metadata__, __request__)
        meter = self.meters.get(key)
        if meter is None:  # no inlet seen (e.g. the module was reloaded mid-stream)
            meter = self.meters[key] = Meter(now, self._label(__model__))
        if meter.reported:
            return event
        meter.add(event, now)
        if meter.exact is not None:  # the usage chunk comes last (after finish_reason, or with it)
            await self._final(key, meter, __event_emitter__, now)
        elif not meter.finished and meter.live_due(
            now, self.valves.update_interval, self.valves.slow_after_updates, self.valves.slow_update_interval
        ):
            meter.last_emit = now
            meter.updates += 1
            await self._status(__event_emitter__, meter.live_text(now), False)
        return event

    async def outlet(self, body: dict, __event_emitter__: Optional[Emitter] = None,
                     __metadata__: Optional[dict] = None, __request__: Any = None) -> dict:
        # The stream ended without a usage block: report the estimate.
        key = self._key(__metadata__, __request__)
        meter = self.meters.get(key)
        if meter is not None:
            await self._final(key, meter, __event_emitter__, meter.t_last if meter.t_last is not None else self.clock())
        return body
