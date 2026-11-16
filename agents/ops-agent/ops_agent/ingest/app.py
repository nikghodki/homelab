"""ops-ingest: Alertmanager webhook receiver + the background sources; opens incidents and starts their workflows."""
from __future__ import annotations

import asyncio
import hmac
import logging

import psycopg
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import Gauge, start_http_server
from temporalio.common import WorkflowIDReusePolicy

from .. import db, mode
from ..config import settings
from ..correlate import from_alertmanager
from ..temporal_client import connect
from . import handler, watchers

log = logging.getLogger("ops-ingest")
G_LEADER = Gauge("ops_ingest_leader", "1 on the replica that runs the watchers")
G_LAST = Gauge("ops_ingest_last_alertmanager_timestamp_seconds", "last webhook from Alertmanager")
app = FastAPI(title="ops-ingest", docs_url=None, redoc_url=None, openapi_url=None)
state: dict = {}


async def start_workflow(inc: dict) -> None:
    from ..worker.workflows import IncidentWorkflow
    c = state["temporal"]
    wid = f"incident-{inc['id']}"
    await c.start_workflow(IncidentWorkflow.run, inc["id"], id=wid, task_queue=settings().task_queue,
                           id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
    db.run("UPDATE incidents SET workflow_id = %s WHERE id = %s", wid, inc["id"])


async def signal_resolve(inc: dict) -> None:
    if not inc.get("workflow_id"):
        return
    try:
        await state["temporal"].get_workflow_handle(inc["workflow_id"]).signal("resolve")
    except Exception as e:
        log.info("resolve signal for %s: %s", inc["workflow_id"], e)


async def handle(ev) -> dict:
    return await handler.handle(ev, start_workflow, signal_resolve)


async def leader_loop() -> None:
    """One replica runs the watchers: whoever holds the advisory lock (a dedicated connection keeps it)."""
    while True:
        try:
            conn = psycopg.connect(settings().db_dsn, autocommit=True)
            if conn.execute("SELECT pg_try_advisory_lock(4343)").fetchone()[0]:
                G_LEADER.set(1)
                log.info("leader: running the watchers")
                await asyncio.gather(watchers.k8s_events(handle), watchers.changes_and_docs(), watchers.github_runs(handle))
            conn.close()
        except Exception as e:
            log.warning("leader loop: %s", e)
        G_LEADER.set(0)
        await asyncio.sleep(30)


@app.on_event("startup")
async def startup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db.migrate()
    start_http_server(9100)
    state["temporal"] = await connect()
    state["leader"] = asyncio.create_task(leader_loop())


@app.get("/healthz")
async def healthz() -> dict:
    db.one("SELECT 1")
    return {"ok": True, "mode": mode.effective()}


@app.post("/hooks/alertmanager")
async def alertmanager(req: Request) -> dict:
    tok = settings().ingest_token
    got = req.headers.get("authorization", "")
    if not tok or not hmac.compare_digest(got, "Bearer " + tok):
        raise HTTPException(status_code=401)
    import time
    G_LAST.set(time.time())
    body = await req.json()
    results = [await handle(ev) for ev in from_alertmanager(body)]
    return {"received": len(results)}
