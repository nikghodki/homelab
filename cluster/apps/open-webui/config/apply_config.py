#!/usr/bin/env python3
"""Apply Open WebUI's settings from Git (settings.yaml) through its admin API, then read them back.

Run by the Job open-webui-config after every Argo CD sync (runbooks/open-webui.md, "Config from Git"). Idempotent:
each step reads the current value and writes only what differs. Open WebUI keeps these settings in its database,
where they win over env vars (a stale OPENAI_API_BASE_URL in the DB once broke every chat), so the check at the end
reads the effective values back from the API, not the env. Secrets (API keys) are read from the environment and are
never printed: the log names keys by their variable and says only "matches" / "differs".

Environment: OWUI_URL (default http://10.43.0.130:8080), OWUI_ADMIN_API_KEY, and the variables named by `key_env` in
settings.yaml. Arguments: --settings (default /config/settings.yaml), --functions-dir (default: next to settings).
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

import yaml

PUBLIC = [{"principal_type": "user", "principal_id": "*", "permission": "read"}]


class ApiError(Exception):
    pass


class Api:
    """Open WebUI's HTTP API (http.client: only http/https, no other URL schemes)."""

    def __init__(self, base: str, key: str, timeout: float = 60.0):
        u = urllib.parse.urlsplit(base)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ApiError(f"OWUI_URL must be http(s)://host[:port], got {base!r}")
        self.scheme, self.host, self.port = u.scheme, u.hostname, u.port
        self.prefix = u.path.rstrip("/")
        self.key = key
        self.timeout = timeout

    def call(self, method: str, path: str, body: Any = None, query: Optional[dict] = None,
             ok: tuple = (200,)) -> tuple[int, Any]:
        target = self.prefix + path + ("?" + urllib.parse.urlencode(query) if query else "")
        conn_cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(self.host, self.port, timeout=self.timeout)
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, target, body=data, headers=headers)
            resp = conn.getresponse()
            status, raw = resp.status, resp.read()
        finally:
            conn.close()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw[:200].decode(errors="replace")
        if status not in ok:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise ApiError(f"{method} {path}: HTTP {status}: {str(detail)[:300]}")
        return status, payload

    def get(self, path, **kw):
        return self.call("GET", path, **kw)[1]

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body=body, **kw)[1]


def log(msg: str) -> None:
    print(msg, flush=True)


# --- pure helpers (unit-tested)

def access_grants(access: Any, group_ids: dict[str, str]) -> list[dict]:
    """settings.yaml `access` -> Open WebUI access grants. public | private | {groups: [...], users: [...]}"""
    if access == "public":
        return list(PUBLIC)
    if access in (None, "private"):
        return []
    if isinstance(access, dict):
        out = []
        for name in access.get("groups") or []:
            if name not in group_ids:
                raise ValueError(f"access names unknown group {name!r}")
            out.append({"principal_type": "group", "principal_id": group_ids[name], "permission": "read"})
        for uid in access.get("users") or []:
            out.append({"principal_type": "user", "principal_id": uid, "permission": "read"})
        return out
    raise ValueError(f"unknown access {access!r}")


def grant_set(grants: list[dict] | None) -> set[tuple]:
    return {(g.get("principal_type"), g.get("principal_id"), g.get("permission")) for g in grants or []}


def desired_connections(spec: list[dict], env: dict) -> tuple[list[str], list[str], dict]:
    urls, keys, configs = [], [], {}
    for i, c in enumerate(spec):
        urls.append(c["url"])
        name = c.get("key_env")
        if name and not env.get(name):
            raise ValueError(f"connection {i} ({c['url']}): environment variable {name} is empty")
        keys.append(env.get(name, "") if name else "")
        configs[str(i)] = dict(c.get("config") or {})
    return urls, keys, configs


def connections_differ(current: dict, urls: list, keys: list, configs: dict) -> list[str]:
    """What differs between GET /openai/config and the desired lists (key values never appear in the result)."""
    out = []
    if current.get("ENABLE_OPENAI_API") is not True:
        out.append("ENABLE_OPENAI_API")
    if list(current.get("OPENAI_API_BASE_URLS") or []) != urls:
        out.append("OPENAI_API_BASE_URLS")
    cur_keys = list(current.get("OPENAI_API_KEYS") or [])
    for i, k in enumerate(keys):
        if i >= len(cur_keys) or cur_keys[i] != k:
            out.append(f"OPENAI_API_KEYS[{i}]")
    if len(cur_keys) != len(keys) and f"OPENAI_API_KEYS[{len(keys)}]" not in out:
        out.append("OPENAI_API_KEYS (length)")
    cur_cfg = current.get("OPENAI_API_CONFIGS") or {}
    for idx, want in configs.items():
        have = cur_cfg.get(idx) or {}
        for k, v in want.items():
            if have.get(k) != v:
                out.append(f"OPENAI_API_CONFIGS[{idx}].{k}")
    for idx in cur_cfg:
        if idx not in configs:
            out.append(f"OPENAI_API_CONFIGS[{idx}] (extra)")
    return out


def model_form(spec: dict, current: Optional[dict]) -> dict:
    meta = dict((current or {}).get("meta") or {})
    meta["description"] = spec.get("description")
    if "capabilities" in spec:
        meta["capabilities"] = dict(spec["capabilities"])
    return {
        "id": spec["id"],
        "base_model_id": spec.get("base_model_id"),
        "name": spec["name"],
        "meta": meta,
        "params": (current or {}).get("params") or {},
        "is_active": True,
    }


def model_differs(spec: dict, current: Optional[dict]) -> list[str]:
    if current is None:
        return ["missing"]
    out = []
    if current.get("name") != spec["name"]:
        out.append("name")
    if current.get("base_model_id") != spec.get("base_model_id"):
        out.append("base_model_id")
    if not current.get("is_active"):
        out.append("is_active")
    meta = current.get("meta") or {}
    if meta.get("description") != spec.get("description"):
        out.append("description")
    if "capabilities" in spec and (meta.get("capabilities") or {}) != spec["capabilities"]:
        out.append("capabilities")
    return out


# --- steps

def wait_ready(api: Api, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            api.call("GET", "/health")
            return
        except (ApiError, OSError, http.client.HTTPException) as e:
            if time.monotonic() > deadline:
                raise ApiError(f"Open WebUI not healthy after {timeout:.0f} s: {e}") from e
            time.sleep(5)


def check_admin(api: Api) -> None:
    # /api/v1/auths/ wants a human session; /api/v1/users/all answers only admins
    users = (api.get("/api/v1/users/all") or {}).get("users") or []
    log(f"admin API key ok ({len(users)} accounts, {sum(u.get('role') == 'admin' for u in users)} admin)")


def ensure_api_keys(api: Api, spec: dict) -> None:
    cfg = api.get("/api/v1/auths/admin/config")
    want = {
        "ENABLE_API_KEYS": bool(spec.get("enable", True)),
        "ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS": bool(spec.get("endpoint_restrictions", True)),
        "API_KEYS_ALLOWED_ENDPOINTS": ",".join(spec.get("allowed_endpoints") or []),
    }
    diff = [k for k, v in want.items() if cfg.get(k) != v]
    if diff:
        cfg.update(want)
        api.post("/api/v1/auths/admin/config", cfg)
        log(f"api keys: set {', '.join(diff)}")
    else:
        log("api keys: unchanged")


def ensure_groups(api: Api, spec: list[dict]) -> dict[str, str]:
    groups = {g["name"]: g for g in api.get("/api/v1/groups/") or []}
    users = (api.get("/api/v1/users/all") or {}).get("users") or []
    admins = sorted(u["id"] for u in users if u.get("role") == "admin")
    ids = {}
    for g in spec:
        name = g["name"]
        if name not in groups:
            created = api.post("/api/v1/groups/create", {"name": name, "description": g.get("description", "")})
            groups[name] = created
            log(f"group {name}: created")
        gid = groups[name]["id"]
        ids[name] = gid
        if groups[name].get("description") != g.get("description", ""):
            api.post(f"/api/v1/groups/id/{gid}/update", {"name": name, "description": g.get("description", "")})
            log(f"group {name}: description updated")
        if g.get("members") == "admins":
            members = api.post(f"/api/v1/groups/id/{gid}/users") or []
            have = sorted(u["id"] for u in members)
            add = [u for u in admins if u not in have]
            remove = [u for u in have if u not in admins]
            if add:
                api.post(f"/api/v1/groups/id/{gid}/users/add", {"user_ids": add})
            if remove:
                api.post(f"/api/v1/groups/id/{gid}/users/remove", {"user_ids": remove})
            log(f"group {name}: {len(admins)} member(s) (admins only); added {len(add)}, removed {len(remove)}")
    return ids


def ensure_functions(api: Api, spec: list[dict], fdir: Path) -> None:
    for f in spec:
        content = (fdir / f["file"]).read_text(encoding="utf-8")
        form = {"id": f["id"], "name": f["name"], "content": content,
                "meta": {"description": f.get("description", ""), "manifest": {}}}
        status, cur = api.call("GET", f"/api/v1/functions/id/{f['id']}", ok=(200, 401, 404))
        if status != 200 or not cur:
            api.post("/api/v1/functions/create", form)
            log(f"function {f['id']}: created")
            cur = api.get(f"/api/v1/functions/id/{f['id']}")
        elif cur.get("content") != content or cur.get("name") != f["name"] or \
                (cur.get("meta") or {}).get("description") != form["meta"]["description"]:
            api.post(f"/api/v1/functions/id/{f['id']}/update", form)
            log(f"function {f['id']}: updated from Git")
            cur = api.get(f"/api/v1/functions/id/{f['id']}")
        else:
            log(f"function {f['id']}: unchanged")
        # the toggles flip the flag, so only call them when it is wrong
        if bool(cur.get("is_active")) != bool(f.get("active", True)):
            api.post(f"/api/v1/functions/id/{f['id']}/toggle")
            log(f"function {f['id']}: active -> {f.get('active', True)}")
        if bool(cur.get("is_global")) != bool(f.get("global", False)):
            api.post(f"/api/v1/functions/id/{f['id']}/toggle/global")
            log(f"function {f['id']}: global -> {f.get('global', False)}")


def ensure_models(api: Api, spec: list[dict], group_ids: dict[str, str]) -> None:
    for m in spec:
        want = access_grants(m.get("access"), group_ids)
        status, cur = api.call("GET", "/api/v1/models/model", query={"id": m["id"]}, ok=(200, 401, 404))
        cur = cur if status == 200 and isinstance(cur, dict) and cur.get("id") == m["id"] else None
        diff = model_differs(m, cur)
        if cur is None:
            api.post("/api/v1/models/create", {**model_form(m, None), "access_grants": want})
            log(f"model {m['id']}: created as {m['name']!r}")
        elif diff:
            api.post("/api/v1/models/model/update", model_form(m, cur))
            log(f"model {m['id']}: updated ({', '.join(diff)})")
        cur = api.get("/api/v1/models/model", query={"id": m["id"]})
        if grant_set(cur.get("access_grants")) != grant_set(want):
            api.post("/api/v1/models/model/access/update", {"id": m["id"], "name": m["name"], "access_grants": want})
            log(f"model {m['id']}: access set to {m.get('access')}")
            diff = diff or ["access"]
        if not diff:
            log(f"model {m['id']}: unchanged")


def ensure_connections(api: Api, spec: list[dict], env: dict) -> None:
    urls, keys, configs = desired_connections(spec, env)
    current = api.get("/openai/config")
    diff = connections_differ(current, urls, keys, configs)
    if diff:
        api.post("/openai/config/update", {"ENABLE_OPENAI_API": True, "OPENAI_API_BASE_URLS": urls,
                                           "OPENAI_API_KEYS": keys, "OPENAI_API_CONFIGS": configs})
        log(f"connections: set {', '.join(diff)}")
    else:
        log("connections: unchanged")


def ensure_model_defaults(api: Api, default_models: Optional[str], order: Optional[list]) -> None:
    cfg = api.get("/api/v1/configs/models")
    want = dict(cfg)
    if default_models is not None:
        want["DEFAULT_MODELS"] = default_models
    if order is not None:
        want["MODEL_ORDER_LIST"] = order
    if want != cfg:
        api.post("/api/v1/configs/models", want)
        log(f"default model {default_models}, order {order}: set")
    else:
        log("default model and order: unchanged")


def verify(api: Api, s: dict, env: dict, group_ids: dict[str, str]) -> list[str]:
    """Read the effective settings back; returns the problems (empty = all good)."""
    problems = []
    urls, keys, configs = desired_connections(s.get("connections") or [], env)
    current = api.get("/openai/config")
    problems += [f"connection {d} not as in Git" for d in connections_differ(current, urls, keys, configs)]
    for i, u in enumerate(current.get("OPENAI_API_BASE_URLS") or []):
        log(f"effective connection {i}: {u} (key {'matches ' + s['connections'][i]['key_env'] if i < len(keys) and (current.get('OPENAI_API_KEYS') or [])[i] == keys[i] else 'DIFFERS'})")
    listed = {m["id"]: m for m in (api.get("/api/models") or {}).get("data", [])}
    for m in s.get("models") or []:
        got = listed.get(m["id"])
        if got is None:
            problems.append(f"model {m['id']} not in /api/models (connection down?)")
            continue
        info = got.get("info") or {}
        log(f"effective model {m['id']}: {got.get('name')!r}, access {sorted(grant_set(info.get('access_grants')))}")
        if got.get("name") != m["name"]:
            problems.append(f"model {m['id']} is named {got.get('name')!r}")
    for f in s.get("functions") or []:
        status, cur = api.call("GET", f"/api/v1/functions/id/{f['id']}", ok=(200, 401, 404))
        if status != 200 or not cur:
            problems.append(f"function {f['id']} missing")
            continue
        log(f"effective function {f['id']}: active={cur.get('is_active')} global={cur.get('is_global')}")
        if bool(cur.get("is_active")) != bool(f.get("active", True)) or \
                bool(cur.get("is_global")) != bool(f.get("global", False)):
            problems.append(f"function {f['id']} flags not as in Git")
    cfg = api.get("/api/v1/configs/models")
    log(f"effective default model: {cfg.get('DEFAULT_MODELS')}")
    if s.get("default_models") and cfg.get("DEFAULT_MODELS") != s["default_models"]:
        problems.append("default model not as in Git")
    return problems


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settings", type=Path, default=Path("/config/settings.yaml"))
    ap.add_argument("--functions-dir", type=Path, default=None)
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--wait", type=float, default=600.0, help="seconds to wait for /health")
    args = ap.parse_args(argv)
    s = yaml.safe_load(args.settings.read_text(encoding="utf-8"))
    fdir = args.functions_dir or args.settings.parent
    key = os.environ.get("OWUI_ADMIN_API_KEY", "")
    if not key.startswith("sk-"):
        log("OWUI_ADMIN_API_KEY is missing or not an Open WebUI API key")
        return 2
    api = Api(os.environ.get("OWUI_URL", "http://10.43.0.130:8080"), key)
    env = dict(os.environ)
    try:
        wait_ready(api, args.wait)
        check_admin(api)
        if not args.verify_only:
            ensure_api_keys(api, s.get("api_keys") or {})
        group_ids = ensure_groups(api, s.get("groups") or []) if not args.verify_only else \
            {g["name"]: g["id"] for g in api.get("/api/v1/groups/") or []}
        if not args.verify_only:
            # Models first (with their access), then connections: a new connection's models are never unregistered
            ensure_functions(api, s.get("functions") or [], fdir)
            ensure_models(api, s.get("models") or [], group_ids)
            ensure_connections(api, s.get("connections") or [], env)
            ensure_model_defaults(api, s.get("default_models"), s.get("model_order"))
        problems = verify(api, s, env, group_ids)
    except (ApiError, ValueError, OSError, http.client.HTTPException) as e:
        log(f"FAILED: {e}")
        return 1
    if problems:
        for p in problems:
            log(f"PROBLEM: {p}")
        return 1
    log("Open WebUI matches Git")
    return 0


if __name__ == "__main__":
    sys.exit(main())
