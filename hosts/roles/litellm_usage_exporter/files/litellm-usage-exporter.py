#!/usr/bin/env python3
"""Who called the model API: LiteLLM's spend log and key aliases as Prometheus metrics (runbooks/litellm.md).

Polls LiteLLM's Postgres every `POLL_S` seconds as the read-only role `litellm_usage_ro` (SELECT on a few columns
of "LiteLLM_SpendLogs" and "LiteLLM_VerificationToken" only) and serves /metrics on 127.0.0.1 for the host
collector. Never reads prompts, replies or a full key hash: the SQL itself cuts the hash to its first 8 hex digits,
the same `api_key_hash` the front door logs (runbooks/edge.md "Access log").

  litellm_usage_key_info{key_alias, api_key_hash} 1           every virtual key (the alias <-> hash8 map)
  litellm_usage_requests_total{key_alias, api_key_hash, model, status, src}   counter, from this exporter's start
  litellm_usage_tokens_total{key_alias, model, kind}           counter (kind: prompt | completion)
  litellm_usage_request_duration_seconds{model}               histogram of successful requests
  litellm_usage_last24h_requests{key_alias, model, status, src}  gauge: rows of the last 24 h (exact, from the DB)
  litellm_usage_last24h_tokens{key_alias, kind}                gauge
  litellm_usage_db_up, litellm_usage_last_poll_timestamp_seconds

`src` names the caller's host from requester_ip_address (the front door's X-Forwarded-For: a k3s node's
pod-network address, SRC_NODES; loopback and Docker bridge addresses are dgx-1 itself; anything else as is).
A key hash column that isn't a 64-digit hex hash is never cut into a label (it could be a raw key): "nonhash".

Counters count rows first seen after start (rows are written in batches, so each poll looks back `LOOKBACK_S` and
skips request_ids it has already counted). Managed by homelab Ansible (roles/litellm_usage_exporter).
"""
import http.server
import os
import pathlib
import threading
import time

POLL_S = int(os.environ.get("POLL_S", "30"))
LOOKBACK_S = int(os.environ.get("LOOKBACK_S", "900"))
PORT = int(os.environ.get("PORT", "9112"))
# pod-network prefix -> node (runbooks/edge.md "Access log"); overridden by SRC_NODES="10.42.1.=dgx-1,..."
SRC_NODES = dict(kv.split("=", 1) for kv in os.environ.get(
    "SRC_NODES", "10.42.1.=dgx-1,10.42.0.=dgx-2,10.42.2.=jetson,10.42.3.=dell").split(",") if "=" in kv)
LOCAL_NAME = os.environ.get("SRC_LOCAL", "dgx-1 (local)")
BUCKETS = (0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300, 600)

HASH8 = ("case when {col} ~ '^[0-9a-f]{{64}}$' then left({col}, 8) "
         "when coalesce({col}, '') <> '' then 'nonhash' end")
KEYS_SQL = f'select key_alias, {HASH8.format(col="token")} from "LiteLLM_VerificationToken"'
COLS = (f"request_id, metadata->>'user_api_key_alias', {HASH8.format(col='api_key')}, model_group, status, "
        "prompt_tokens, completion_tokens, request_duration_ms, "
        'extract(epoch from ("endTime" - "startTime")) * 1000, requester_ip_address')
# startTime is UTC without a time zone (LiteLLM writes it so)
RECENT_SQL = (f'select {COLS} from "LiteLLM_SpendLogs" '
              "where \"startTime\" > (now() at time zone 'utc') - make_interval(secs => %s)")
DAY_SQL = (f"select metadata->>'user_api_key_alias', {HASH8.format(col='api_key')}, model_group, status, "
           "requester_ip_address, count(*), coalesce(sum(prompt_tokens), 0), coalesce(sum(completion_tokens), 0) "
           'from "LiteLLM_SpendLogs" '
           "where \"startTime\" > (now() at time zone 'utc') - interval '24 hours' group by 1, 2, 3, 4, 5")


def who(alias, hash8) -> str:
    """The name a caller is shown under: its key alias, else its hash8, else "(not a virtual key)" (e.g. the master
    key or LiteLLM's own calls) or "(no key)" (refused before auth)."""
    if alias:
        return alias
    if hash8 == "nonhash":
        return "(not a virtual key)"
    return f"key:{hash8}" if hash8 else "(no key)"


def source(ip) -> str:
    """The calling host for requester_ip_address (see the module docstring)."""
    ip = (ip or "").strip()
    if not ip:
        return "(unknown)"
    for prefix, node in SRC_NODES.items():
        if ip.startswith(prefix):
            return node
    if ip in ("127.0.0.1", "::1") or ip.startswith("172.") and 16 <= int((ip.split(".") + ["0", "0"])[1] or 0) <= 31:
        return LOCAL_NAME
    return ip


def status_of(status) -> str:
    return status if status in ("success", "failure") else "unknown"


def esc(v) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def labels(**kv) -> str:
    return "{" + ",".join(f'{k}="{esc(v)}"' for k, v in kv.items()) + "}"


class Usage:
    def __init__(self):
        self.lock = threading.Lock()
        self.seen = {}            # request_id -> first-seen monotonic time
        self.primed = False       # the first poll only remembers rows (no double count after a restart)
        self.requests = {}        # (who, hash8, model, status, src) -> n
        self.tokens = {}          # (who, model, kind) -> n
        self.hist = {}            # model -> [bucket counts..., +Inf count, sum]
        self.keys = []
        self.day_requests = {}
        self.day_tokens = {}
        self.up = 0
        self.last_poll = 0.0

    def add_rows(self, rows, now=None) -> int:
        """Count spend-log rows not seen before; returns how many were new."""
        now = time.monotonic() if now is None else now
        new = 0
        with self.lock:
            for rid, alias, hash8, model, status, ptok, ctok, dur_ms, span_ms, ip in rows:
                if rid in self.seen:
                    continue
                self.seen[rid] = now
                if not self.primed:
                    continue
                new += 1
                name, model, st = who(alias, hash8), model or "(none)", status_of(status)
                k = (name, hash8 if hash8 and hash8 != "nonhash" else "", model, st, source(ip))
                self.requests[k] = self.requests.get(k, 0) + 1
                for kind, n in (("prompt", ptok), ("completion", ctok)):
                    if n:
                        tk = (name, model, kind)
                        self.tokens[tk] = self.tokens.get(tk, 0) + int(n)
                ms = dur_ms if dur_ms is not None else span_ms
                if st == "success" and ms is not None:
                    secs = float(ms) / 1000
                    h = self.hist.setdefault(model, [0] * (len(BUCKETS) + 1) + [0.0])
                    for i, b in enumerate(BUCKETS):
                        if secs <= b:
                            h[i] += 1
                    h[len(BUCKETS)] += 1
                    h[-1] += secs
            self.primed = True
            # forget ids older than the look-back window (twice it, to be safe)
            cutoff = now - 2 * LOOKBACK_S
            for rid in [r for r, t in self.seen.items() if t < cutoff]:
                del self.seen[rid]
        return new

    def set_snapshot(self, keys, day_rows) -> None:
        req, tok = {}, {}
        for alias, hash8, model, status, ip, n, ptok, ctok in day_rows:
            name = who(alias, hash8)
            k = (name, model or "(none)", status_of(status), source(ip))
            req[k] = req.get(k, 0) + int(n)
            for kind, v in (("prompt", ptok), ("completion", ctok)):
                tok[(name, kind)] = tok.get((name, kind), 0) + int(v or 0)
        with self.lock:
            self.keys = sorted({(alias or f"key:{h}", h) for alias, h in keys if h and h != "nonhash"})
            self.day_requests, self.day_tokens = req, tok

    def render(self) -> str:
        with self.lock:
            out = ["# TYPE litellm_usage_db_up gauge", f"litellm_usage_db_up {self.up}",
                   "# TYPE litellm_usage_last_poll_timestamp_seconds gauge",
                   f"litellm_usage_last_poll_timestamp_seconds {self.last_poll:.0f}",
                   "# TYPE litellm_usage_key_info gauge"]
            out += [f"litellm_usage_key_info{labels(key_alias=a, api_key_hash=h)} 1" for a, h in self.keys]
            out.append("# TYPE litellm_usage_requests_total counter")
            out += [f"litellm_usage_requests_total{labels(key_alias=w, api_key_hash=h, model=m, status=s, src=src)} {n}"
                    for (w, h, m, s, src), n in sorted(self.requests.items())]
            out.append("# TYPE litellm_usage_tokens_total counter")
            out += [f"litellm_usage_tokens_total{labels(key_alias=w, model=m, kind=k)} {n}"
                    for (w, m, k), n in sorted(self.tokens.items())]
            out.append("# TYPE litellm_usage_request_duration_seconds histogram")
            for model, h in sorted(self.hist.items()):
                for i, b in enumerate(BUCKETS):
                    out.append(f"litellm_usage_request_duration_seconds_bucket{labels(model=model, le=b)} {h[i]}")
                out.append(f"litellm_usage_request_duration_seconds_bucket{labels(model=model, le='+Inf')} {h[len(BUCKETS)]}")
                out.append(f"litellm_usage_request_duration_seconds_count{labels(model=model)} {h[len(BUCKETS)]}")
                out.append(f"litellm_usage_request_duration_seconds_sum{labels(model=model)} {h[-1]:.3f}")
            out.append("# TYPE litellm_usage_last24h_requests gauge")
            out += [f"litellm_usage_last24h_requests{labels(key_alias=w, model=m, status=s, src=src)} {n}"
                    for (w, m, s, src), n in sorted(self.day_requests.items())]
            out.append("# TYPE litellm_usage_last24h_tokens gauge")
            out += [f"litellm_usage_last24h_tokens{labels(key_alias=w, kind=k)} {n}"
                    for (w, k), n in sorted(self.day_tokens.items())]
        return "\n".join(out) + "\n"


def connect():
    import psycopg2  # python3-psycopg2 (apt); imported here so the tests need no driver
    password = (pathlib.Path(os.environ["CREDENTIALS_DIRECTORY"]) / "db-password").read_text().strip()
    return psycopg2.connect(host=os.environ.get("PGHOST", "127.0.0.1"), port=int(os.environ.get("PGPORT", "5432")),
                            dbname=os.environ.get("PGDATABASE", "litellm"),
                            user=os.environ.get("PGUSER", "litellm_usage_ro"), password=password,
                            connect_timeout=10, application_name="litellm-usage-exporter")


def poll(usage: Usage, conn) -> None:
    with conn.cursor() as cur:
        cur.execute(RECENT_SQL, (LOOKBACK_S,))
        recent = cur.fetchall()
        cur.execute(KEYS_SQL)
        keys = cur.fetchall()
        cur.execute(DAY_SQL)
        day = cur.fetchall()
    conn.rollback()  # read-only; end the transaction so each poll sees new rows
    usage.add_rows(recent)
    usage.set_snapshot(keys, day)


def loop(usage: Usage) -> None:
    conn = None
    while True:
        try:
            if conn is None or conn.closed:
                conn = connect()
            poll(usage, conn)
            usage.up, usage.last_poll = 1, time.time()
        except Exception as e:  # noqa: BLE001 - keep serving; report the DB as down
            usage.up = 0
            print(f"poll failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
            try:
                if conn is not None:
                    conn.close()
            except Exception:  # noqa: BLE001
                pass
            conn = None
        time.sleep(POLL_S)


def serve(usage: Usage) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path != "/metrics":
                self.send_error(404)
                return
            body = usage.render().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    u = Usage()
    threading.Thread(target=loop, args=(u,), daemon=True).start()
    serve(u)
