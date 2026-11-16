"""One incident, end to end: first look -> recall -> investigate -> RCA. Shared by the Temporal activities and the
replay harness, so a replay exercises exactly the code that runs live."""
from __future__ import annotations

import datetime as dt
from typing import Callable

from . import db, mode, playbooks, timeutil
from .correlate import host_of
from .config import settings
from .investigate import own_loop, prompts
from .tools.gateway import Gateway, ToolContext


def load_incident(incident_id: int) -> tuple[dict, list[dict]]:
    inc = db.one("SELECT * FROM incidents WHERE id = %s", incident_id)
    if not inc:
        raise LookupError(f"incident {incident_id} not found")
    events = db.all_("SELECT * FROM events WHERE incident_id = %s ORDER BY occurred_at", incident_id)
    return inc, events


async def first_look(gw: Gateway, ctx: ToolContext, inc: dict) -> tuple[str, str]:
    ctx.phase = "first_look"
    steps, runbook_q = playbooks.steps_for(inc["klass"], inc["labels"] or {}, host_of(inc["labels"] or {}))
    parts = []
    for st in steps:
        ref, text, _ok = await gw.call(ctx, st["tool"], st["args"])
        parts.append(text)
    return "\n\n".join(parts), runbook_q


async def recall(gw: Gateway, ctx: ToolContext, inc: dict, runbook_q: str) -> str:
    ctx.phase = "recall"
    out = []
    q = runbook_q or inc["title"]
    _r, t, _ = await gw.call(ctx, "runbooks", {"query": q})
    out.append(t)
    _r, t, _ = await gw.call(ctx, "past_incidents", {"query": inc["title"].split(":")[0]})
    out.append(t)
    return "\n\n".join(out)


def budget_ok() -> bool:
    return db.tokens_today() < settings().daily_token_budget


async def analyse(incident_id: int, *, engine: str = "own-loop", as_of: dt.datetime | None = None,
                  docs_commit: str | None = None, frozen: dict | None = None,
                  may_continue: Callable[[], bool] | None = None) -> int:
    """Run the whole investigation and store an RCA row. Returns the RCA id."""
    inc, events = load_incident(incident_id)
    gw = Gateway()
    ctx = ToolContext(incident_id=incident_id, as_of=as_of, docs_commit=docs_commit, frozen=frozen or {})
    db.run("UPDATE incidents SET status = 'investigating', updated_at = now() WHERE id = %s", incident_id)
    try:
        fl, rq = await first_look(gw, ctx, inc)
        rc = await recall(gw, ctx, inc, rq)
        go = may_continue or (lambda: mode.running() and budget_ok())
        clock = timeutil.iso(as_of) if as_of else "now (live)"
        if not go():
            rca_id = store_rca(incident_id, "deterministic", None, deterministic_rca(inc, ctx), [], 0, 0, 0.0)
        elif engine == "holmesgpt":
            from .investigate import holmes  # only in the replay/bake-off environment
            res = await holmes.investigate(gw, ctx, prompts.incident_brief(inc, events, clock), fl, rc)
            rca_id = store_rca(incident_id, engine, settings().model_deep, res.rca, res.notes, res.tokens,
                               res.tool_calls, res.seconds)
        else:
            ctx.phase = "investigate"
            res = await own_loop.investigate(gw, ctx, prompts.incident_brief(inc, events, clock), fl, rc,
                                             may_continue=go, engine=engine)
            known = {r["ref"] for r in db.all_("SELECT ref FROM evidence WHERE incident_id = %s", incident_id)}
            rca = own_loop.self_check(res.rca, known) if res.rca else deterministic_rca(inc, ctx, res.notes)
            rca["trace"] = res.trace[-30:]
            rca_id = store_rca(incident_id, engine if res.rca else "deterministic", settings().model_deep, rca,
                               res.notes, res.tokens, res.tool_calls, res.seconds)
    finally:
        await gw.close()
    db.run("UPDATE incidents SET status = CASE WHEN status = 'investigating' THEN 'rca_ready' ELSE status END, "
           "updated_at = now() WHERE id = %s", incident_id)
    return rca_id


def deterministic_rca(inc: dict, ctx: ToolContext, notes: list[str] | None = None) -> dict:
    """Evidence without analysis (model down, budget used up, or stopped): design §8.4, decision 0013 Q6."""
    ev = db.all_("SELECT ref, tool, ok FROM evidence WHERE incident_id = %s ORDER BY id", inc["id"])
    return {"summary": f"{inc['title']}: evidence collected, no model analysis", "confidence": "none",
            "root_cause": "not analysed (" + ("; ".join(notes) if notes else "model unavailable or budget used up") + ")",
            "claims": [], "fix_options": [{"description": "read the first-look evidence and the linked runbook", "kind": "manual"}],
            "evidence_refs": [e["ref"] for e in ev], "deterministic": True}


def store_rca(incident_id: int, engine: str, model: str | None, rca: dict, notes: list[str], tokens: int,
              tool_calls: int, seconds: float) -> int:
    md = own_loop.to_markdown(rca, engine, notes)
    r = db.one("INSERT INTO rcas (incident_id, engine, model, confidence, summary, body, markdown, tokens, tool_calls, seconds) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
               incident_id, engine, model, rca.get("confidence", "none"), str(rca.get("summary", ""))[:1000],
               db.j({**rca, "notes": notes}), md, tokens, tool_calls, seconds)
    db.audit(engine, "rca.stored", {"incident": incident_id, "rca": r["id"], "tokens": tokens, "tool_calls": tool_calls})
    return r["id"]
