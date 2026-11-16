"""Postgres access (psycopg 3). One small pool per process; every helper is synchronous and short."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import settings

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(settings().db_dsn, min_size=1, max_size=4, kwargs={"row_factory": dict_row},
                               open=True)
    return _pool


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    with pool().connection() as c:
        yield c


def migrate() -> None:
    sql = (Path(__file__).parent / "schema.sql").read_text()
    with conn() as c:
        c.execute("SELECT pg_advisory_lock(4242)")
        try:
            c.execute(sql)
        finally:
            c.execute("SELECT pg_advisory_unlock(4242)")


def one(q: str, *a: Any) -> dict | None:
    with conn() as c:
        return c.execute(q, a).fetchone()


def all_(q: str, *a: Any) -> list[dict]:
    with conn() as c:
        return c.execute(q, a).fetchall()


def run(q: str, *a: Any) -> None:
    with conn() as c:
        c.execute(q, a)


def j(v: Any) -> Jsonb:
    return Jsonb(v)


# --- mode (the Stop switch) -------------------------------------------------------------------------------------

def db_mode() -> str:
    r = one("SELECT value FROM settings WHERE key = 'mode'")
    return (r or {}).get("value") or "shadow"


def set_mode(mode: str, actor: str) -> None:
    assert mode in ("shadow", "stopped")
    run("INSERT INTO settings (key, value, updated_by) VALUES ('mode', %s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now(), updated_by = EXCLUDED.updated_by",
        j(mode), actor)
    audit(actor, "mode." + mode, {})


# --- audit (append-only, hash chain) ----------------------------------------------------------------------------

def audit(actor: str, action: str, detail: dict) -> None:
    with conn() as c:
        c.execute("LOCK TABLE audit IN SHARE ROW EXCLUSIVE MODE")
        prev = c.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = prev["hash"] if prev else "0" * 64
        at = dt.datetime.now(dt.timezone.utc).isoformat()
        h = hashlib.sha256(json.dumps([prev_hash, at, actor, action, detail], sort_keys=True,
                                      default=str).encode()).hexdigest()
        c.execute("INSERT INTO audit (at, actor, action, detail, prev_hash, hash) VALUES (%s, %s, %s, %s, %s, %s)",
                  (at, actor, action, j(detail), prev_hash, h))


def verify_audit() -> tuple[bool, int]:
    rows = all_("SELECT at, actor, action, detail, prev_hash, hash FROM audit ORDER BY id")
    prev = "0" * 64
    for r in rows:
        at = r["at"].isoformat()
        h = hashlib.sha256(json.dumps([prev, at, r["actor"], r["action"], r["detail"]], sort_keys=True,
                                      default=str).encode()).hexdigest()
        if r["prev_hash"] != prev or r["hash"] != h:
            return False, len(rows)
        prev = h
    return True, len(rows)


# --- LLM usage and the daily budget (decision 0013 Q13) ---------------------------------------------------------

def add_usage(engine: str, model: str, prompt: int, completion: int) -> None:
    run("INSERT INTO llm_usage (day, engine, model, calls, prompt_tokens, completion_tokens) "
        "VALUES (current_date, %s, %s, 1, %s, %s) ON CONFLICT (day, engine, model) DO UPDATE SET "
        "calls = llm_usage.calls + 1, prompt_tokens = llm_usage.prompt_tokens + EXCLUDED.prompt_tokens, "
        "completion_tokens = llm_usage.completion_tokens + EXCLUDED.completion_tokens",
        engine, model, prompt, completion)


def tokens_today() -> int:
    r = one("SELECT coalesce(sum(prompt_tokens + completion_tokens), 0) AS t FROM llm_usage WHERE day = current_date")
    return int(r["t"]) if r else 0
