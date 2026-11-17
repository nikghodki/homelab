"""Counting and status logic of the TPS meter filter (tps_meter.py), with a fake clock and a fake event emitter."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tps_meter as tm  # noqa: E402


def delta(text=None, reasoning=None, finish=None, usage=None):
    d = {}
    if text is not None:
        d["content"] = text
    if reasoning is not None:
        d["reasoning_content"] = reasoning
    chunk = {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": d, "finish_reason": finish}]}
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def usage_only(n):  # LiteLLM / vLLM with include_usage: choices [] and the usage block, after finish_reason
    return {"object": "chat.completion.chunk", "choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": n,
                                                                        "total_tokens": 9 + n}}


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


class Run:
    """Drives a Filter the way Open WebUI does: inlet, stream per chunk, outlet."""

    def __init__(self, model_id="qwen3.8-27b", message_id="m1", **valves):
        self.f = tm.Filter()
        for k, v in valves.items():
            setattr(self.f.valves, k, v)
        self.clock = Clock()
        self.f.clock = self.clock
        self.events = []
        self.meta = {"chat_id": "c1", "message_id": message_id}
        self.model = {"id": model_id}

    async def emit(self, event):
        self.events.append((self.clock.t, event))

    def statuses(self):
        return [(t, e["data"]["description"], e["data"]["done"]) for t, e in self.events if e["type"] == "status"]

    def inlet(self):
        asyncio.run(self.f.inlet({"messages": []}, __metadata__=self.meta, __model__=self.model))

    def chunk(self, at, chunk):
        self.clock.t = at
        out = asyncio.run(self.f.stream(chunk, __event_emitter__=self.emit, __metadata__=self.meta,
                                        __model__=self.model))
        assert out is chunk  # the filter never changes the stream

    def outlet(self, at):
        self.clock.t = at
        asyncio.run(self.f.outlet({}, __event_emitter__=self.emit, __metadata__=self.meta))


# --- pure helpers

def test_chunk_text_content_reasoning_tool_calls():
    c = {"choices": [{"delta": {"content": "Hi", "reasoning_content": "think",
                                "tool_calls": [{"function": {"name": "f", "arguments": "{}"}}]}}]}
    assert tm.chunk_text(c) == "Hithinkf{}"
    assert tm.chunk_text({"choices": [{"delta": {"role": "assistant"}}]}) == ""
    assert tm.chunk_text({"choices": None}) == ""
    assert tm.chunk_text({"usage": {"completion_tokens": 3}}) == ""


def test_chunk_usage_variants():
    assert tm.chunk_usage(usage_only(7)) == 7
    assert tm.chunk_usage({"usage": {"output_tokens": 5}}) == 5
    assert tm.chunk_usage({"usage": {"completion_tokens": True}}) is None
    assert tm.chunk_usage({"usage": None}) is None
    assert tm.chunk_usage({}) is None


def test_estimate_tokens():
    assert tm.estimate_tokens("") == 0
    assert tm.estimate_tokens("a") == 1  # a chunk is at least one token
    assert tm.estimate_tokens("x" * 40) == 10


def test_formats():
    assert tm.fmt_seconds(0.412) == "0.41 s"
    assert tm.fmt_seconds(13.84) == "13.8 s"
    assert tm.fmt_seconds(265) == "4 min 25 s"
    assert tm.fmt_rate(38.25) == "38.2"
    assert tm.fmt_rate(212.4) == "212"


# --- exact usage (direct model through LiteLLM)

def test_exact_usage_after_finish_chunk():
    r = Run()
    r.inlet()                                   # t0 = 100
    r.chunk(100.5, delta(reasoning="Let"))      # first token: TTFT 0.5 s
    for i in range(1, 10):
        r.chunk(100.5 + i * 0.1, delta(text="ab"))
    r.chunk(101.4, delta(finish="stop"))
    r.chunk(101.4, usage_only(20))              # exact: 20 tokens over 0.9 s
    final = r.statuses()[-1]
    assert final[2] is True
    assert final[1] == "22.2 tok/s · 20 output tokens · first token 0.50 s · 1.40 s total"
    assert "≈" not in final[1]
    r.outlet(102.0)                              # already reported: nothing more
    assert sum(1 for s in r.statuses() if s[2]) == 1
    assert r.f.meters == {}


def test_usage_in_the_finish_chunk_hermes_style_with_label():
    r = Run(model_id="hermes.hermes-agent")
    r.inlet()
    r.chunk(102.0, delta(text="hello"))
    r.chunk(104.0, delta(text=" there"))
    r.chunk(104.0, delta(finish="stop", usage={"prompt_tokens": 13856, "completion_tokens": 6, "total_tokens": 13862}))
    final = r.statuses()[-1]
    assert final[1].startswith("Agent run: 3.0 tok/s · 6 output tokens · first token 2.00 s")
    assert final[2] is True


# --- estimate (no usage block)

def test_estimate_when_no_usage_is_labelled_and_reported_by_outlet():
    r = Run()
    r.inlet()
    r.chunk(101.0, delta(text="abcd"))
    r.chunk(102.0, delta(text="efgh"))
    r.chunk(103.0, delta(finish="stop"))
    assert all(not s[2] for s in r.statuses())  # no final yet: waiting for a usage chunk
    r.outlet(110.0)
    final = r.statuses()[-1]
    assert final[2] is True
    assert final[1] == "≈ 2.0 tok/s · ≈ 2 output tokens · first token 1.00 s · 2.00 s total"


def test_nothing_generated_says_nothing():
    r = Run()
    r.inlet()
    r.chunk(101.0, {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]})
    r.outlet(102.0)
    assert r.statuses() == []
    assert r.f.meters == {}


# --- live updates and throttling

def test_live_updates_throttled_to_interval():
    r = Run(update_interval=0.5)
    r.inlet()
    for i in range(30):  # a chunk every 0.1 s for 3 s
        r.chunk(100.0 + i * 0.1, delta(text="x"))
    live = [s for s in r.statuses() if not s[2]]
    assert 6 <= len(live) <= 7
    times = [t for t, _, _ in live]
    assert all(b - a >= 0.5 - 1e-9 for a, b in zip(times, times[1:]))
    assert live[0][1].startswith("first token after")
    assert all(s[1].startswith("≈ ") and "tok/s" in s[1] for s in live[1:])


def test_live_updates_slow_down_after_many():
    r = Run(update_interval=0.5, slow_after_updates=4, slow_update_interval=2.0)
    r.inlet()
    for i in range(100):  # 10 s of chunks
        r.chunk(100.0 + i * 0.1, delta(text="x"))
    times = [t for t, _, d in r.statuses() if not d]
    gaps = [round(b - a, 1) for a, b in zip(times, times[1:])]
    assert gaps[:3] == [0.5, 0.5, 0.5]
    assert all(g >= 2.0 for g in gaps[4:])


def test_live_rate_value():
    r = Run()
    r.inlet()
    r.chunk(101.0, delta(text="x"))
    for i in range(1, 11):
        r.chunk(101.0 + i * 0.1, delta(text="x"))  # 11 tokens over 1 s
    live = [s for s in r.statuses() if not s[2]][-1]
    assert live[1] == "≈ 11.0 tok/s · 11 tokens so far"


def test_no_live_update_after_finish():
    r = Run()
    r.inlet()
    r.chunk(101.0, delta(text="x"))
    r.chunk(101.0, delta(finish="stop"))
    n = len(r.statuses())
    r.chunk(105.0, {"choices": [{"delta": {}, "finish_reason": None}]})
    assert len(r.statuses()) == n


# --- robustness

def test_concurrent_replies_are_kept_apart():
    a, b = Run(message_id="a"), Run(message_id="b")
    b.f = a.f  # one module instance serves every chat
    b.f.clock = a.clock = b.clock
    a.inlet()
    b.inlet()
    a.chunk(101.0, delta(text="aaaa"))
    b.chunk(102.0, delta(text="bbbb"))
    a.chunk(101.5, usage_only(10))
    assert set(a.f.meters) == {"c1:b"}
    b.chunk(103.0, usage_only(4))
    assert a.f.meters == {}


def test_stream_without_inlet_still_measures():
    r = Run()
    r.chunk(101.0, delta(text="x"))
    r.chunk(102.0, usage_only(3))
    assert r.statuses()[-1][2] is True


def test_emitter_failure_does_not_break_the_stream():
    r = Run()

    async def broken(event):
        raise RuntimeError("socket gone")

    r.emit = broken
    r.inlet()
    r.chunk(101.0, delta(text="x"))
    r.chunk(102.0, usage_only(1))


def test_stale_meters_are_pruned():
    r = Run()
    r.inlet()
    r.clock.t += tm.STALE_AFTER_S + 1
    r.meta = {"chat_id": "c1", "message_id": "m2"}
    r.inlet()
    assert set(r.f.meters) == {"c1:m2"}


def test_non_dict_event_passes_through():
    f = tm.Filter()
    assert asyncio.run(f.stream("data")) == "data"


@pytest.mark.parametrize("model_id,label", [("hermes.hermes-agent", "Agent run: "), ("qwen3.8-27b", "")])
def test_label(model_id, label):
    assert tm.Filter()._label({"id": model_id}) == label


def test_first_live_update_reports_the_first_token_time_not_a_rate():
    r = Run()
    r.inlet()
    r.chunk(103.62, delta(text="x"))  # a cold-ish start: first token after 3.62 s
    first = r.statuses()[0]
    assert first == (103.62, "first token after 3.62 s", False)
    for i in range(1, 6):
        r.chunk(103.62 + i * 0.1, delta(text="x"))
    assert r.statuses()[-1][1].startswith("≈ ")
