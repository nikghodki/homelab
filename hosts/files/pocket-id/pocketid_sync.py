#!/usr/bin/env python3
"""Make Pocket ID match identity/pocket-id.yaml (groups, users, OIDC clients).

Idempotent. New client secrets go straight into SOPS (never printed). With
--login-link USER it prints a one-time sign-in link so USER can add a passkey.

Usage: pocketid_sync.py [--dry-run] [--login-link USER]
Env:   POCKETID_URL (default https://id.nghodki.ai); the static API key is read from SOPS.
"""

import argparse
import json
import os
import ssl
import subprocess
import sys
from pathlib import Path

import httpx
import yaml

REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / "identity/pocket-id.yaml"
SECRETS = REPO / "secrets/console.enc.yaml"


def sops_get(key):
    out = subprocess.run(["sops", "-d", "--extract", f'["{key}"]', str(SECRETS)],
                         capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def sops_set(key, value):
    subprocess.run(["sops", "set", str(SECRETS), f'["{key}"]', json.dumps(value)], check=True)


class PocketID:
    def __init__(self, base, api_key, dry_run=False):
        self.http = httpx.Client(base_url=base.rstrip("/") + "/api", headers={"X-API-Key": api_key}, timeout=20,
                                 verify=ssl.create_default_context())  # system store: has the homelab web CA
        self.dry_run = dry_run

    def get(self, path, **params):
        r = self.http.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def send(self, method, path, body=None):
        if self.dry_run and method != "GET":
            print(f"would {method} {path}")
            return {}
        r = self.http.request(method, path, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    def all(self, path):
        data = self.get(path, **{"pagination[limit]": 100})
        return data.get("data", data) if isinstance(data, dict) else data


def sync(api, spec, log=print):
    groups = {g["name"]: g for g in api.all("/user-groups")}
    for g in spec.get("groups", []):
        if g["name"] not in groups:
            groups[g["name"]] = api.send("POST", "/user-groups", g) or {"id": None, **g}
            log(f"group {g['name']}: created")

    users = {u["username"]: u for u in api.all("/users")}
    for u in spec.get("users", []):
        body = {k: v for k, v in u.items() if k != "groups"}
        body.setdefault("emailVerified", True)
        if u["username"] not in users:
            users[u["username"]] = api.send("POST", "/users", body) or {"id": None, **body}
            log(f"user {u['username']}: created")
        uid = users[u["username"]].get("id")
        want = sorted(groups[g]["id"] for g in u.get("groups", []) if groups[g].get("id"))
        have = sorted(g["id"] for g in api.get(f"/users/{uid}/groups")) if uid else []
        if uid and want != have:
            api.send("PUT", f"/users/{uid}/user-groups", {"userGroupIds": want})
            log(f"user {u['username']}: groups set")

    clients = {c["id"]: c for c in api.all("/oidc/clients")}
    for c in spec.get("clients", []):
        body = {"id": c["id"], "name": c["name"], "callbackURLs": c["callbackURLs"],
                "logoutCallbackURLs": c.get("logoutCallbackURLs", []), "launchURL": c.get("launchURL"),
                "isPublic": False, "pkceEnabled": c.get("pkce", True), "skipConsent": True,
                "requiresReauthentication": False, "requiresPushedAuthorizationRequests": False,
                "credentials": {}}
        if c["id"] not in clients:
            api.send("POST", "/oidc/clients", body)
            log(f"client {c['id']}: created")
        else:
            cur = clients[c["id"]]
            if (sorted(cur.get("callbackURLs") or []) != sorted(c["callbackURLs"]) or cur.get("name") != c["name"]
                    or cur.get("pkceEnabled") != body["pkceEnabled"] or cur.get("launchURL") != body["launchURL"]):
                update = {k: v for k, v in body.items() if k != "id"}
                api.send("PUT", f"/oidc/clients/{c['id']}", update)
                log(f"client {c['id']}: updated")
        want = sorted(groups[g]["id"] for g in c.get("groups", []) if groups[g].get("id"))
        api.send("PUT", f"/oidc/clients/{c['id']}/allowed-user-groups", {"userGroupIds": want})
        key = f"oidc_{c['id']}_secret"
        if not api.dry_run and sops_get(key) is None:
            secret = api.send("POST", f"/oidc/clients/{c['id']}/secrets", {})
            sops_set(key, secret["secret"])
            log(f"client {c['id']}: secret created and stored in SOPS as {key}")
    return users


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--login-link", metavar="USER")
    args = ap.parse_args()
    api_key = sops_get("pocketid_static_api_key")
    if not api_key:
        sys.exit("pocketid_static_api_key not found in secrets/console.enc.yaml")
    base = os.environ.get("POCKETID_URL", "https://id.nghodki.ai")
    api = PocketID(base, api_key, args.dry_run)
    users = sync(api, yaml.safe_load(SPEC.read_text()))
    if args.login_link:
        uid = users[args.login_link]["id"]
        token = api.send("POST", f"/users/{uid}/one-time-access-token", {"ttl": "1h"})["token"]
        print(f"{base}/lc/{token}  (valid 1 hour, single use)")


if __name__ == "__main__":
    main()
