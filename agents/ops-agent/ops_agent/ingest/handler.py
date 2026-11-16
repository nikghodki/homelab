"""Event handling: store, correlate into incidents, start one Temporal workflow per new incident (design §4.2)."""
from __future__ import annotations

import datetime as dt
import logging
import time

from prometheus_client import Counter

from .. import db, mode, redact
from ..correlate import Event, StormDetector, change_matches, family_impact, host_of, is_flapping

log = logging.getLogger("ops-ingest")
C_EVENTS = Counter("ops_ingest_events_total", "events received", ["source", "status"])
C_INCIDENTS = Counter("ops_ingest_incidents_total", "incidents opened", ["klass"])
STORM = StormDetector()


def during_change(klass: str, labels: dict, at: dt.datetime) -> str | None:
    rows = db.all_("SELECT at, kind, ref, summary, components FROM changes WHERE at BETWEEN %s AND %s ORDER BY at DESC",
                   at - dt.timedelta(minutes=20), at + dt.timedelta(minutes=2))
    for r in rows:
        if change_matches(klass, labels, r["components"]):
            return f"{r['kind']} {r['ref'][:12]} at {r['at']:%H:%M} UTC: {r['summary'][:120]}"
    return None


def store_event(ev: Event, incident_id: int | None) -> int:
    payload, _ = redact.redact(str(ev.payload))
    r = db.one("INSERT INTO events (occurred_at, source, fingerprint, status, summary, labels, payload_sha, payload, incident_id) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id", ev.occurred_at, ev.source, ev.fingerprint, ev.status,
               redact.clean(ev.summary, 500), db.j(ev.labels), ev.payload_sha, db.j({"redacted": payload[:6000]}), incident_id)
    return r["id"]


def open_incident(key: str) -> dict | None:
    return db.one("SELECT * FROM incidents WHERE key = %s AND replay_run IS NULL AND status IN ('open','investigating','rca_ready')", key)


def create_incident(ev: Event, key: str, title: str, tags: list[str]) -> tuple[dict, bool]:
    fam = family_impact(ev.summary, " ".join(f"{k}={v}" for k, v in ev.labels.items()))
    chg = during_change(ev.klass, ev.labels, ev.occurred_at)
    r = db.one("INSERT INTO incidents (key, title, severity, klass, family_impact, during_change, tags, source, labels, opened_at) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *",
               key, redact.clean(title, 300), ev.severity if ev.severity in ("critical", "warning", "info") else "warning",
               ev.klass, fam, chg, tags + (["during-change"] if chg else []), ev.source, db.j(ev.labels), ev.occurred_at)
    if r:
        C_INCIDENTS.labels(ev.klass).inc()
        db.audit("ingest", "incident.opened", {"incident": r["id"], "key": key, "during_change": bool(chg)})
        return r, True
    return open_incident(key), False


async def handle(ev: Event, start_workflow, signal_resolve) -> dict:
    """Returns a small dict for logs/tests: {event, incident, new, action}."""
    C_EVENTS.labels(ev.source, ev.status).inc()
    key = ev.incident_key()
    if ev.status == "resolved":
        inc = open_incident(key)
        eid = store_event(ev, inc["id"] if inc else None)
        if inc:
            # every alert of the incident resolved? (other fingerprints may still fire)
            firing = db.one("SELECT count(*) AS n FROM (SELECT DISTINCT ON (fingerprint) status FROM events WHERE incident_id = %s "
                            "ORDER BY fingerprint, received_at DESC) s WHERE status = 'firing'", inc["id"])
            if firing["n"] == 0:
                db.run("UPDATE incidents SET status = 'resolved', resolved_at = now(), updated_at = now() WHERE id = %s", inc["id"])
                await signal_resolve(inc)
                return {"event": eid, "incident": inc["id"], "new": False, "action": "resolved"}
        return {"event": eid, "incident": inc and inc["id"], "new": False, "action": "stored"}

    now = time.time()
    storm = STORM.add(now)
    flaps = db.one("SELECT count(*) AS n FROM events WHERE fingerprint = %s AND status = 'firing' AND received_at > now() - interval '1 hour'",
                   ev.fingerprint)["n"]
    inc = open_incident(key)
    if inc is None:
        # host-down folding: everything on a host that is down joins that host's incident
        host = host_of(ev.labels)
        if host and ev.klass != "host_down":
            inc = db.one("SELECT * FROM incidents WHERE klass = 'host_down' AND replay_run IS NULL AND status IN ('open','investigating','rca_ready') "
                         "AND labels->>'host_name' = %s ORDER BY id DESC LIMIT 1", ev.labels.get("host_name", ""))
    if inc is None and storm:
        key = f"storm:{int(STORM.storm_since or now)}"
        inc, new = create_incident(ev, key, f"Alert storm: many events at once (first: {ev.summary[:120]})", ["storm"])
        eid = store_event(ev, inc["id"])
        if new and mode.running():
            await start_workflow(inc)
        return {"event": eid, "incident": inc["id"], "new": new, "action": "storm"}
    if inc is not None:
        eid = store_event(ev, inc["id"])
        if is_flapping(flaps) and "flapping" not in (inc["tags"] or []):
            db.run("UPDATE incidents SET tags = array_append(tags, 'flapping'), updated_at = now() WHERE id = %s", inc["id"])
        db.run("UPDATE incidents SET updated_at = now() WHERE id = %s", inc["id"])
        return {"event": eid, "incident": inc["id"], "new": False, "action": "attached"}
    if is_flapping(flaps):
        # a resolved-then-firing-again alert past the limit becomes one "flapping" item, not one incident each time
        key = f"flapping:{ev.labels.get('alertname', ev.fingerprint)}"
        inc, new = create_incident(ev, key, f"Flapping: {ev.summary[:160]}", ["flapping"])
        eid = store_event(ev, inc["id"])
        return {"event": eid, "incident": inc["id"], "new": new, "action": "flapping"}
    inc, new = create_incident(ev, key, ev.summary, [])
    eid = store_event(ev, inc["id"])
    if new and mode.running():
        await start_workflow(inc)
    return {"event": eid, "incident": inc["id"], "new": new, "action": "opened" if new else "attached"}
