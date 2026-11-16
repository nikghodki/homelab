"""ops-portal: ops-agent.nghodki.ai (decision 0013 Q4). Behind the front door's sign-in (admins); shadow mode, so it
is read-only except for the Stop switch and the ntfy Snooze/Dismiss buttons (which only make the agent do less)."""
from __future__ import annotations

import datetime as dt
import hmac
import secrets
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .. import db, mode
from ..config import settings

app = FastAPI(title="ops-portal", docs_url=None, redoc_url=None, openapi_url=None)
# Starlette's Jinja2Templates autoescapes .html templates.
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
OPEN = ("open", "investigating", "rca_ready")


@app.middleware("http")
async def front_door_only(request: Request, call_next):
    """Every request must come through the front door (it adds the origin token after sign-in); /healthz is for
    the kubelet. Responses are never cached and can't be framed."""
    if request.url.path != "/healthz":
        tok = settings().origin_token
        got = request.headers.get("x-edge-origin", "")
        if not tok or not hmac.compare_digest(got, tok):
            return Response("Use https://ops-agent.nghodki.ai", status_code=403)
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def _csrf(request: Request) -> str:
    return request.cookies.get("ops_csrf") or secrets.token_urlsafe(16)


def _page(request: Request, name: str, **ctx) -> HTMLResponse:
    token = _csrf(request)
    tokens = db.tokens_today()
    ctx.update(request=request, mode=mode.effective(), git_mode=mode.git_mode(), csrf_token=token, tokens=tokens,
               budget=settings().daily_token_budget, now=dt.datetime.now(dt.timezone.utc))
    resp = templates.TemplateResponse(request, name, ctx)
    resp.set_cookie("ops_csrf", token, secure=True, httponly=True, samesite="strict", max_age=86400)
    return resp


def _check_csrf(request: Request, form_token: str) -> None:
    if not form_token or not hmac.compare_digest(form_token, request.cookies.get("ops_csrf", "")):
        raise HTTPException(status_code=400, detail="stale form; reload the page")


@app.get("/healthz")
async def healthz() -> dict:
    db.one("SELECT 1")
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def feed(request: Request):
    open_ = db.all_("SELECT i.*, r.summary AS rca_summary, r.confidence, r.engine FROM incidents i LEFT JOIN LATERAL "
                    "(SELECT summary, confidence, engine FROM rcas WHERE incident_id = i.id ORDER BY id DESC LIMIT 1) r ON true "
                    "WHERE i.replay_run IS NULL AND i.status IN ('open','investigating','rca_ready') ORDER BY "
                    "i.family_impact DESC, (i.severity = 'critical') DESC, i.opened_at DESC LIMIT 50")
    resolved = db.all_("SELECT i.*, r.summary AS rca_summary, r.confidence FROM incidents i LEFT JOIN LATERAL "
                       "(SELECT summary, confidence FROM rcas WHERE incident_id = i.id ORDER BY id DESC LIMIT 1) r ON true "
                       "WHERE i.replay_run IS NULL AND i.status IN ('resolved','closed') AND i.updated_at > now() - interval '48 hours' "
                       "ORDER BY i.updated_at DESC LIMIT 30")
    last_event = db.one("SELECT max(received_at) AS t, count(*) FILTER (WHERE received_at > now() - interval '24 hours') AS n FROM events")
    notes = db.one("SELECT count(*) FILTER (WHERE state = 'sent' AND created_at > now() - interval '24 hours') AS sent, "
                   "count(*) FILTER (WHERE state = 'held') AS held FROM notifications")
    return _page(request, "feed.html", open=open_, resolved=resolved, last_event=last_event, notes=notes)


@app.get("/incidents/{iid}", response_class=HTMLResponse)
async def incident(request: Request, iid: int):
    inc = db.one("SELECT * FROM incidents WHERE id = %s", iid)
    if not inc:
        raise HTTPException(404)
    rcas = db.all_("SELECT * FROM rcas WHERE incident_id = %s ORDER BY id DESC", iid)
    evidence = db.all_("SELECT * FROM evidence WHERE incident_id = %s ORDER BY id", iid)
    events = db.all_("SELECT * FROM events WHERE incident_id = %s ORDER BY occurred_at", iid)
    pm = db.one("SELECT markdown FROM postmortems WHERE incident_id = %s ORDER BY id DESC LIMIT 1", iid)
    notes = db.all_("SELECT * FROM notifications WHERE incident_id = %s ORDER BY id", iid)
    return _page(request, "incident.html", inc=inc, rcas=rcas, evidence=evidence, events=events, postmortem=pm, notes=notes)


@app.get("/replay", response_class=HTMLResponse)
async def replay(request: Request):
    runs = db.all_("SELECT * FROM replay_runs ORDER BY id DESC LIMIT 20")
    results = db.all_("SELECT r.*, i.title FROM replay_results r LEFT JOIN incidents i ON i.id = r.incident_id "
                      "ORDER BY r.run_id DESC, r.gold_id")
    return _page(request, "replay.html", runs=runs, results=results)


@app.get("/audit", response_class=HTMLResponse)
async def audit(request: Request):
    rows = db.all_("SELECT * FROM audit ORDER BY id DESC LIMIT 200")
    ok, n = db.verify_audit()
    return _page(request, "audit.html", rows=rows, chain_ok=ok, chain_n=n)


@app.post("/stop")
async def stop(request: Request, csrf_token: str = Form("")):
    _check_csrf(request, csrf_token)
    db.set_mode("stopped", "portal (front-door admin)")
    return RedirectResponse("/", status_code=303)


@app.post("/resume")
async def resume(request: Request, csrf_token: str = Form(""), confirm: str = Form("")):
    _check_csrf(request, csrf_token)
    if confirm != "resume":
        raise HTTPException(400, "type resume to confirm")
    db.set_mode("shadow", "portal (front-door admin)")
    return RedirectResponse("/", status_code=303)


@app.post("/ntfy-action/{token}/{what}")
async def ntfy_action(token: str, what: str):
    """ntfy's http buttons (decision 0013 Q9): Snooze 1 h or Dismiss for one incident. Each message carries its own
    random token; a token works for its incident only and only makes the agent quieter. Never an approval."""
    if what not in ("snooze", "dismiss") or len(token) < 16:
        raise HTTPException(404)
    n = db.one("SELECT incident_id FROM notifications WHERE action_token = %s", token)
    if not n or not n["incident_id"]:
        raise HTTPException(404)
    if what == "snooze":
        db.run("UPDATE incidents SET snoozed_until = now() + interval '1 hour' WHERE id = %s", n["incident_id"])
    else:
        db.run("UPDATE incidents SET dismissed = true WHERE id = %s", n["incident_id"])
    db.audit("ntfy", f"incident.{what}", {"incident": n["incident_id"]})
    return JSONResponse({"ok": True})
