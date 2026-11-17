"""Our own investigation loop: plain OpenAI-compatible tool calling against LiteLLM (design §5.2, Q5 candidate)."""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI

from .. import db, redact
from ..config import settings
from ..tools.gateway import TOOL_SPECS, Gateway, ToolContext
from . import prompts


@dataclass
class LoopResult:
    rca: dict
    tokens: int = 0
    tool_calls: int = 0
    seconds: float = 0.0
    refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)   # per turn: finish reason, tool names, the start of any text


def client() -> AsyncOpenAI:
    s = settings()
    return AsyncOpenAI(base_url=s.llm_base, api_key=s.llm_key, timeout=httpx.Timeout(900, connect=10), max_retries=1)


async def chat(llm: AsyncOpenAI, model: str, messages: list[dict], tools: list[dict] | None = None,
               tool_choice=None, max_tokens: int = 12000, engine: str = "own-loop"):
    kw = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
    if tools:
        kw["tools"] = [{"type": "function", "function": t} for t in tools]
        kw["tool_choice"] = tool_choice or "auto"
    # The shared model plane drops connections now and then (engine restarts, queueing) and the key's own rate
    # limits answer 429: back off and retry a few times before giving up on the call.
    for attempt, wait in enumerate((15, 45, 90, 120, 180, None)):
        try:
            r = await llm.chat.completions.create(**kw)
            break
        except APIConnectionError:
            if wait is None:
                raise
        except APIStatusError as e:
            if wait is None or e.status_code not in (429, 500, 502, 503, 504):
                raise
        await asyncio.sleep(wait)
    u = r.usage
    if u:
        db.add_usage(engine, model, u.prompt_tokens or 0, u.completion_tokens or 0)
    return r, (u.total_tokens if u else 0)


async def investigate(gw: Gateway, ctx: ToolContext, brief: str, first_look: str, recall: str, *,
                      may_continue: Callable[[], bool], clock: Callable[[], str] | None = None,
                      engine: str = "own-loop") -> LoopResult:
    s = settings()
    llm = client()
    t0 = time.monotonic()
    res = LoopResult(rca={})
    messages = [{"role": "system", "content": prompts.SYSTEM},
                {"role": "user", "content": f"{brief}\n\nFIRST LOOK (deterministic queries):\n{first_look}\n\n"
                                            f"RECALL (runbooks, past incidents):\n{recall}\n\nInvestigate, then call submit_rca."}]
    tools = TOOL_SPECS + [prompts.SUBMIT_RCA]
    forced = False
    length_retries = 0
    last_prompt = 0
    while True:
        # stop before the next call would cross the cap (each call re-sends the conversation)
        over = (res.tool_calls >= s.max_tool_calls or res.tokens + int(last_prompt * 1.3) >= s.incident_token_cap
                or time.monotonic() - t0 > s.investigation_minutes * 60)
        if not may_continue():
            res.notes.append("stopped by the Stop switch or the daily token budget")
            break
        choice = {"type": "function", "function": {"name": "submit_rca"}} if (over or forced) else None
        try:
            r, n = await chat(llm, s.model_deep, messages, tools, tool_choice=choice, engine=engine)
        except APIStatusError as e:
            body = str(getattr(e, "body", "") or e)[:400]
            if e.status_code == 400 and "DefenseClaw" in body:
                # The guardrail refused our prompt: the evidence probably carries an injection. Record it and finish
                # with what we have instead of re-sending the same text.
                res.notes.append("DefenseClaw blocked a prompt built from the evidence (possible injection): "
                                 + redact.clean(body, 300))
                break
            res.notes.append(f"model call failed: HTTP {e.status_code}")
            break
        except (httpx.HTTPError, APIConnectionError) as e:
            res.notes.append(f"model unreachable: {type(e).__name__}")
            break
        res.tokens += n
        last_prompt = (r.usage.prompt_tokens if r.usage else 0) or last_prompt
        msg = r.choices[0].message
        calls = msg.tool_calls or []
        res.trace.append(f"{r.choices[0].finish_reason}: {[c.function.name for c in calls]} {(msg.content or '')[:160]!r}")
        if not calls and r.choices[0].finish_reason == "length" and length_retries < 2:
            # the reasoning used up the output budget before any answer: ask for the next step without the long think
            messages.append({"role": "user", "content": "Your reasoning ran out of space. Decide now: call the next "
                             "tool, or submit_rca if the evidence is enough. Keep any reasoning short."})
            length_retries += 1
            continue
        if not calls:
            got = _json_answer(msg.content or "")
            if got:
                res.rca = got
                break
            if forced:
                break
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({"role": "user", "content": "Call submit_rca now with your conclusion."})
            forced = True
            continue
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                        for c in calls]})
        done = False
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except ValueError:
                args = {}
            if c.function.name == "submit_rca":
                res.rca = args
                done = True
                messages.append({"role": "tool", "tool_call_id": c.id, "content": "received"})
                continue
            if res.tool_calls >= s.max_tool_calls:
                messages.append({"role": "tool", "tool_call_id": c.id,
                                 "content": "tool budget used up; call submit_rca now"})
                continue
            res.tool_calls += 1
            ref, text, _ok = await gw.call(ctx, c.function.name, args)
            res.refs.append(ref)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": text})
        _shrink_old_results(messages, keep=6)
        if done:
            break
    if not res.rca and not any(n.startswith(("DefenseClaw", "stopped")) for n in res.notes):
        # Named tool_choice isn't honoured by every engine: ask once more for the JSON itself, without tools.
        try:
            messages.append({"role": "user", "content": "Time is up. Reply with ONLY the JSON object of your RCA "
                             "(keys: summary, impact, root_cause, confidence, claims[{claim, evidence}], timeline, "
                             "ruled_out, fix_options[{description, kind, risk}], verification, follow_ups, needs)."})
            r, n = await chat(llm, s.model_fast, messages, max_tokens=3000, engine=engine)
            res.tokens += n
            text = r.choices[0].message.content or ""
            res.rca = _json_answer(text)
            if res.rca:
                res.notes.append("RCA returned as text after the tool budget")
            else:
                res.notes.append("no RCA: the final answer wasn't the JSON asked for: " + redact.clean(text, 400))
        except Exception as e:
            res.notes.append(f"final answer failed: {type(e).__name__}")
    if res.rca:
        try:
            r, n = await chat(llm, s.model_fast, [
                {"role": "system", "content": "You review incident analyses for over-claiming."},
                {"role": "user", "content": prompts.SECOND_LOOK + "\n\n" + json.dumps(res.rca)[:12000]}],
                max_tokens=400, engine=engine)
            res.tokens += n
            res.rca["second_look"] = (r.choices[0].message.content or "").strip()
        except Exception as e:  # the second look is a bonus
            res.notes.append(f"second look skipped: {type(e).__name__}")
    res.seconds = time.monotonic() - t0
    return res


def _shrink_old_results(messages: list[dict], keep: int = 6, head: int = 400) -> None:
    """Each call re-sends the conversation, so tokens grow with the square of the tool calls. Results older than
    the last `keep` are cut to their first `head` characters; the model can still cite them (the ref stays) and the
    full text is in the evidence store."""
    tools = [m for m in messages if m.get("role") == "tool" and len(m.get("content") or "") > head + 80]
    for m in tools[:-keep] if len(tools) > keep else []:
        c = m["content"]
        ref = c.split(" ", 2)[1] if c.startswith("<<<EVIDENCE") else ""
        m["content"] = c[:head] + f"\n[older result shortened to save tokens; full text is evidence {ref}]"


def _json_answer(text: str) -> dict:
    """The last JSON object in a text that looks like an RCA (has root_cause)."""
    import re as _re
    for m in reversed(list(_re.finditer(r"\{", text))):
        depth = 0
        for i, ch in enumerate(text[m.start():]):
            depth += (ch == "{") - (ch == "}")
            if depth == 0:
                try:
                    d = json.loads(text[m.start():m.start() + i + 1])
                except ValueError:
                    break
                if isinstance(d, dict) and "root_cause" in d:
                    return d
                break
    return {}


def self_check(rca: dict, known_refs: set[str]) -> dict:
    """Keep only claims whose evidence refs exist; uncited claims are moved to `uncited` (design §5.2)."""
    kept, dropped = [], []
    for c in rca.get("claims") or []:
        if isinstance(c, str):
            c = {"claim": c, "evidence": c}
        # evidence may come as a list, a string ("E1, E3") or inside the claim text: take every E<n> it names
        cited = sorted(set(re.findall(r"\bE\d+\b", json.dumps(c.get("evidence") or "") + " " + str(c.get("claim", "")))),
                       key=lambda r: int(r[1:]))
        refs = [r for r in cited if r in known_refs]
        (kept if refs else dropped).append({**c, "evidence": refs or cited})
    rca["claims"], rca["uncited"] = kept, dropped
    if not kept and rca.get("confidence") == "high":
        rca["confidence"] = "low"
    return rca


def to_markdown(rca: dict, engine: str, notes: list[str] | None = None) -> str:
    def item(x) -> str:
        if isinstance(x, dict):
            return " ".join(str(v) for v in x.values() if v not in (None, "", []))
        if isinstance(x, list):
            return "; ".join(item(v) for v in x)
        return str(x)
    if not rca:
        return "No RCA: " + "; ".join(notes or ["the model gave no answer"])
    L = [f"**{rca.get('summary', '')}**", "", f"Confidence: **{rca.get('confidence', '?')}** ({engine})", ""]
    if rca.get("impact"):
        L += [f"Impact: {item(rca['impact'])}", ""]
    L += ["Root cause: " + item(rca.get("root_cause", "")), ""]
    if rca.get("claims"):
        L.append("Claims:")
        L += [f"- {c.get('claim')} [{', '.join(c.get('evidence') or [])}]" for c in rca["claims"]]
        L.append("")
    if rca.get("uncited"):
        L.append("Removed (no valid evidence): " + "; ".join(c.get("claim", "") for c in rca["uncited"]))
        L.append("")
    for k, title in (("timeline", "Timeline"), ("ruled_out", "Ruled out"), ("follow_ups", "Follow-ups"), ("needs", "Would need")):
        if rca.get(k):
            L.append(title + ":")
            L += [f"- {item(x)}" for x in (rca[k] if isinstance(rca[k], list) else [rca[k]])]
            L.append("")
    if rca.get("fix_options"):
        L.append("Fix options (proposals; shadow mode executes nothing):")
        L += [f"- [{f.get('kind')}] {f.get('description')}" + (f" (risk: {f['risk']})" if f.get("risk") else "")
              if isinstance(f, dict) else f"- {f}" for f in rca["fix_options"]]
        L.append("")
    if rca.get("verification"):
        v = rca["verification"]
        L += ["Verify: " + ("; ".join(map(item, v)) if isinstance(v, list) else item(v)), ""]
    if rca.get("second_look"):
        L += ["Second look: " + str(rca["second_look"]), ""]
    if notes:
        L += ["Notes: " + "; ".join(notes)]
    return "\n".join(L)
