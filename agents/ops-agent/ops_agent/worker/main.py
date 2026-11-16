"""ops-worker: the Temporal worker, the Stop switch watcher, the heartbeat and the agent's own metrics.

Two task queues: `ops-agent` (workflows and the short activities) and `ops-investigate` (one investigation at a time
per replica; 2 replicas = 2 in flight, decision 0013 Q13).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

import httpx
from prometheus_client import Gauge, start_http_server
from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleSpec, ScheduleCalendarSpec, ScheduleRange
from temporalio.worker import Worker

from .. import db, mode, notify
from ..config import settings
from ..temporal_client import connect
from . import activities as A
from .workflows import INVESTIGATE_QUEUE, DigestWorkflow, IncidentWorkflow

log = logging.getLogger("ops-worker")
G_MODE = Gauge("ops_agent_mode", "1 = shadow (running), 0 = stopped")
G_RUNNING = Gauge("ops_agent_worker_polling", "1 while the Temporal worker polls")
G_TOKENS = Gauge("ops_agent_llm_tokens_today", "LLM tokens used today")
G_BUDGET = Gauge("ops_agent_llm_token_budget", "daily LLM token budget")
G_OPEN = Gauge("ops_agent_incidents_open", "open incidents")
G_INV = Gauge("ops_agent_investigations_running", "incidents being investigated")
G_STUCK = Gauge("ops_agent_investigation_oldest_seconds", "age of the oldest running investigation")
G_HB = Gauge("ops_agent_heartbeat_timestamp_seconds", "last successful heartbeat")


async def ensure_schedules(client) -> None:
    sid = "ops-agent-digest"
    h = client.get_schedule_handle(sid)
    try:
        d = await h.describe()
        if getattr(d.schedule.action, "task_queue", settings().task_queue) == settings().task_queue:
            return
        await h.delete()   # created by another task queue (a test): recreate it for this one
    except Exception:
        pass
    await client.create_schedule(sid, Schedule(
        action=ScheduleActionStartWorkflow(DigestWorkflow.run, id="ops-agent-digest", task_queue=settings().task_queue),
        spec=ScheduleSpec(calendars=[ScheduleCalendarSpec(hour=[ScheduleRange(8)], minute=[ScheduleRange(0)])],
                          time_zone_name=settings().timezone)))
    log.info("created schedule %s (08:00 %s)", sid, settings().timezone)


async def cancel_running(client) -> int:
    n = 0
    async for wf in client.list_workflows("ExecutionStatus = 'Running' AND WorkflowType = 'IncidentWorkflow'"):
        await client.get_workflow_handle(wf.id).cancel()
        n += 1
    return n


async def heartbeat(client) -> None:
    s = settings()
    ok, err = True, ""
    try:
        await client.service_client.check_health()
    except Exception as e:
        ok, err = False, f"temporal: {type(e).__name__}"
    try:
        db.one("SELECT 1")
    except Exception as e:
        ok, err = False, f"database: {type(e).__name__}"
    if not s.heartbeat_url:
        return
    params = {"success": "true" if ok else "false"}
    if not ok:
        params["error"] = err
    if mode.effective() == "stopped":
        params["error"] = "agent stopped (Stop switch)"
    try:
        r = httpx.post(s.heartbeat_url, params=params, headers={"Authorization": "Bearer " + s.heartbeat_token}, timeout=10)
        if r.status_code < 300 and ok:
            G_HB.set(dt.datetime.now().timestamp())
    except httpx.HTTPError:
        pass


def gauges() -> None:
    G_TOKENS.set(db.tokens_today())
    G_BUDGET.set(settings().daily_token_budget)
    r = db.one("SELECT count(*) FILTER (WHERE status IN ('open','investigating','rca_ready')) AS open, "
               "count(*) FILTER (WHERE status = 'investigating') AS inv, "
               "extract(epoch FROM now() - min(updated_at) FILTER (WHERE status = 'investigating')) AS oldest "
               "FROM incidents WHERE replay_run IS NULL")
    G_OPEN.set(r["open"])
    G_INV.set(r["inv"])
    G_STUCK.set(float(r["oldest"] or 0))


def release_held_criticals() -> None:
    if notify.in_quiet_hours():
        return
    for n in db.all_("SELECT id, incident_id, title, body, priority FROM notifications WHERE state = 'held' "
                     "AND priority = 'high' AND reason LIKE 'critical, but quiet hours%%'"):
        ok, _ = notify.publish(n["title"], n["body"], "high", n["incident_id"], tags="mag")
        db.run("UPDATE notifications SET state = %s WHERE id = %s", "released" if ok else "held", n["id"])


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = settings()
    db.migrate()
    start_http_server(9100)
    client = await connect()
    await ensure_schedules(client)
    acts = [A.notify_incident, A.close_incident, A.send_digest]
    workers: list[Worker] = []
    tasks: list[asyncio.Task] = []
    last_hb = 0.0
    while True:
        m = mode.effective()
        G_MODE.set(1 if m != "stopped" else 0)
        if m != "stopped" and not workers:
            workers = [Worker(client, task_queue=s.task_queue, workflows=[IncidentWorkflow, DigestWorkflow], activities=acts,
                              max_concurrent_activities=4),
                       Worker(client, task_queue=INVESTIGATE_QUEUE, activities=[A.analyse_incident],
                              max_concurrent_activities=1)]
            tasks = [asyncio.create_task(w.run()) for w in workers]
            log.info("polling (mode %s)", m)
            G_RUNNING.set(1)
        elif m == "stopped" and workers:
            n = await cancel_running(client)
            for w in workers:
                await w.shutdown()
            workers, tasks = [], []
            G_RUNNING.set(0)
            db.audit("worker", "worker.stopped", {"cancelled_workflows": n})
            log.warning("STOPPED: cancelled %d workflows, no longer polling", n)
        try:
            gauges()
            if m != "stopped":
                release_held_criticals()
        except Exception as e:
            log.warning("gauges: %s", e)
        now = asyncio.get_running_loop().time()
        if now - last_hb > 300:
            await heartbeat(client)
            last_hb = now
        for t in tasks:
            if t.done() and t.exception():
                raise t.exception()
        await asyncio.sleep(5)


def run() -> None:
    asyncio.run(main())
