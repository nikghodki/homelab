"""Activities: the side-effecting work of the workflows. Each one checks the Stop switch first."""
from __future__ import annotations

import asyncio
import datetime as dt

from temporalio import activity
from temporalio.exceptions import ApplicationError

from .. import db, mode, notify, pipeline


def _stopped() -> None:
    if not mode.running():
        raise ApplicationError("the agent is stopped", type="Stopped", non_retryable=True)


@activity.defn
async def analyse_incident(incident_id: int) -> int:
    _stopped()

    async def beat() -> None:
        while True:
            activity.heartbeat()
            await asyncio.sleep(20)

    hb = asyncio.create_task(beat())

    def may_continue() -> bool:
        return (not activity.is_cancelled()) and mode.running() and pipeline.budget_ok()

    try:
        return await pipeline.analyse(incident_id, may_continue=may_continue)
    finally:
        hb.cancel()


@activity.defn
async def notify_incident(incident_id: int) -> str:
    _stopped()
    inc = db.one("SELECT * FROM incidents WHERE id = %s", incident_id)
    rca = db.one("SELECT body FROM rcas WHERE incident_id = %s ORDER BY id DESC LIMIT 1", incident_id)
    return notify.for_incident(inc, (rca or {}).get("body"))


@activity.defn
async def close_incident(incident_id: int) -> str:
    inc = db.one("SELECT * FROM incidents WHERE id = %s", incident_id)
    rca = db.one("SELECT markdown, summary FROM rcas WHERE incident_id = %s ORDER BY id DESC LIMIT 1", incident_id)
    db.run("UPDATE incidents SET status = 'closed', updated_at = now(), resolved_at = coalesce(resolved_at, now()) "
           "WHERE id = %s", incident_id)
    # Postmortem (decision 0013 Q11: in shadow mode it goes to the agent's database, not a PR).
    ev = db.all_("SELECT occurred_at, source, status, summary FROM events WHERE incident_id = %s ORDER BY occurred_at", incident_id)
    md = [f"# INC-{incident_id}: {inc['title']}", "",
          f"- Opened {inc['opened_at']:%Y-%m-%d %H:%M} UTC, closed {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC",
          f"- Severity {inc['severity']}, class {inc['klass']}, family-facing: {inc['family_impact']}",
          f"- During a change: {inc['during_change'] or 'no'}", "", "## Timeline", ""]
    md += [f"- {e['occurred_at']:%m-%d %H:%M} {e['source']} {e['status']}: {e['summary'][:200]}" for e in ev]
    md += ["", "## Analysis", "", (rca or {}).get("markdown") or "(no RCA)"]
    db.run("INSERT INTO postmortems (incident_id, markdown) VALUES (%s, %s)", incident_id, "\n".join(md))
    db.audit("worker", "incident.closed", {"incident": incident_id})
    return "closed"


@activity.defn
async def send_digest() -> str:
    if not mode.running():
        return "stopped"
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    opened = db.all_("SELECT i.id, i.title, i.severity, i.status, r.summary, r.confidence FROM incidents i "
                     "LEFT JOIN LATERAL (SELECT summary, confidence FROM rcas WHERE incident_id = i.id ORDER BY id DESC LIMIT 1) r ON true "
                     "WHERE i.replay_run IS NULL AND i.opened_at > %s ORDER BY i.id", since)
    still = db.one("SELECT count(*) AS n FROM incidents WHERE replay_run IS NULL AND status IN ('open','investigating','rca_ready')")
    tokens = db.tokens_today()
    lines = [f"Last 24 h: {len(opened)} incident(s); {still['n']} open. LLM yesterday/today: {tokens} tokens."]
    for i in opened[:12]:
        lines.append(f"- INC-{i['id']} {i['severity']} {i['status']}: {i['title'][:90]}"
                     + (f" -> ({i['confidence']}) {i['summary'][:140]}" if i['summary'] else ""))
    if len(opened) > 12:
        lines.append(f"... and {len(opened) - 12} more in the portal")
    if not opened:
        lines.append("Quiet day: nothing to report.")
    lines.append("Shadow mode: nothing was changed.")
    ok, _ = notify.publish("Ops agent: morning digest", "\n".join(lines), "default", None, tags="sunrise")
    db.run("UPDATE notifications SET state = 'digested' WHERE state = 'held' AND created_at < now()")
    return "sent" if ok else "failed"
