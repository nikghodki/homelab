"""ntfy topic ops-agent (design §7.3, decision 0013 Q9/Q10).

Shadow mode (S1): family-facing incidents and critical RCAs are sent at once (family-facing ones even in quiet hours);
everything else is held for the 08:00 digest. Buttons: "Open" (view, the portal) and http "Snooze 1 h" / "Dismiss",
which only make the agent do less; there is never an Approve button.
"""
from __future__ import annotations

import datetime as dt
import secrets
from zoneinfo import ZoneInfo

import httpx

from . import db, redact
from .config import settings

PRIO = {"urgent": "5", "high": "4", "default": "3", "low": "2"}


def in_quiet_hours(now: dt.datetime | None = None) -> bool:
    s = settings()
    t = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo(s.timezone)).time()
    a = dt.time.fromisoformat(s.quiet_start)
    b = dt.time.fromisoformat(s.quiet_end)
    return (t >= a or t < b) if a > b else (a <= t < b)


def decide(kind: str, severity: str, family: bool, now: dt.datetime | None = None) -> tuple[str, str, str]:
    """(state, priority, reason). state: send | held."""
    if family:
        return "send", "urgent", "family-facing service: always notify (Q10)"
    if kind == "digest":
        return "send", "default", "morning digest"
    if kind == "agent":
        return "send", "high", "about the agent itself"
    if severity == "critical":
        if in_quiet_hours(now):
            return "held", "high", "critical, but quiet hours (22:30-07:30): sent at 07:30"
        return "send", "high", "critical incident"
    return "held", "default", "shadow mode: warnings and info go to the 08:00 digest"


def publish(title: str, body: str, priority: str, incident_id: int | None = None, tags: str = "") -> tuple[bool, str]:
    s = settings()
    action = secrets.token_urlsafe(16) if incident_id else None
    headers = {"Title": redact.clean(title, 200), "Priority": PRIO.get(priority, "3"), "Markdown": "yes"}
    if tags:
        headers["Tags"] = tags
    if s.ntfy_token:
        headers["Authorization"] = "Bearer " + s.ntfy_token
    if incident_id:
        url = f"{s.portal_url}/incidents/{incident_id}"
        headers["Click"] = url
        headers["Actions"] = (f"view, Open, {url}; "
                              f"http, Snooze 1 h, {s.portal_url}/ntfy-action/{action}/snooze, method=POST, clear=true; "
                              f"http, Dismiss, {s.portal_url}/ntfy-action/{action}/dismiss, method=POST, clear=true")
    text = redact.clean(body, 3500)
    try:
        r = httpx.post(f"{s.ntfy_url}/{s.ntfy_topic}", content=text.encode(), headers=headers, timeout=15)
        ok = r.status_code < 300
        err = "" if ok else f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        ok, err = False, type(e).__name__
    db.run("INSERT INTO notifications (incident_id, kind, priority, title, body, state, reason, action_token, sent_at) "
           "VALUES (%s, 'message', %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END)",
           incident_id, priority, title[:200], text[:4000], "sent" if ok else "failed", err or None, action, ok)
    return ok, err


def record_held(incident_id: int | None, kind: str, priority: str, title: str, body: str, reason: str) -> None:
    db.run("INSERT INTO notifications (incident_id, kind, priority, title, body, state, reason) VALUES (%s,%s,%s,%s,%s,'held',%s)",
           incident_id, kind, priority, title[:200], redact.clean(body, 4000), reason)


def for_incident(inc: dict, rca: dict | None) -> str:
    """Notify (or hold) for an incident whose RCA is ready. Returns the decision."""
    if inc.get("snoozed_until") and inc["snoozed_until"] > dt.datetime.now(dt.timezone.utc):
        return "snoozed"
    if inc.get("dismissed"):
        return "dismissed"
    state, prio, reason = decide("rca", inc["severity"], inc["family_impact"])
    title = f"INC-{inc['id']} {inc['severity']}: {inc['title']}"[:180]
    summary = (rca or {}).get("summary") or "evidence collected; no analysis"
    conf = (rca or {}).get("confidence", "none")
    body = f"{summary}\n\nConfidence: {conf}. Shadow mode: nothing was changed."
    if inc.get("during_change"):
        body += f"\nDuring a change: {inc['during_change']}"
    if state == "send":
        publish(title, body, prio, inc["id"], tags="mag")
    else:
        record_held(inc["id"], "rca", prio, title, body, reason)
    return state
