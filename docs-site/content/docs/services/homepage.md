---
title: Homepage (ops.nghodki.ai)
description: The launcher at ops.nghodki.ai on the Dell, signed in at the front door (edge-auth, Pocket ID).
---

Homepage is the interim "single pane of glass" launcher until the Fleet Console exists (D23, UI design open).

| | |
|---|---|
| URL | `https://ops.nghodki.ai` (http → https) |
| Host | the Dell, stack `ops` (`hosts/stacks/ops`, `playbooks/ops.yml`, `/opt/homelab/ops`); moved from dgx-2 in PR #55 |
| Containers | `homepage` (`ghcr.io/gethomepage/homepage:v2.8.0`, no ports, `HOMEPAGE_ALLOWED_HOSTS=ops.nghodki.ai`); its gate is the ops stack's `docs` Caddy on 192.168.86.49:4180 (passes only requests with the front door's `X-Edge-Origin` token, else 403) |
| Sign-in | the front door: `import signed_in 192.168.86.49:4180 admins` (client `edge-auth`, cookie `_edge_auth` for `.nghodki.ai`, 7 days, shared with the docs, Gatus and MLflow) |
| Secrets | `edge_origin_token` (`secrets/console.enc.yaml`), rendered into the gate |
| Host overrides | `extra_hosts` send every `*.nghodki.ai` name its siteMonitors use to the in-cluster front door's VIP `192.168.86.11` (until 2026-11-15 they pointed at dgx-1's old door) |
| Config | `homepage/services.yaml` (tiles), `settings.yaml`, `widgets.yaml` (date and search only), `bookmarks.yaml` (empty) |
| Health | Gatus `ops.nghodki.ai (Homepage)` expects 302 to Pocket ID when signed out; `Homepage gate refuses direct access` expects 403 |

Tiles (with a `siteMonitor` each, mostly through the front door): Observe (Grafana, Status, Phoenix, ntfy), Models (Open
WebUI, LiteLLM, DGXMM), ML (MLflow; its monitor uses the job API's open `/health` on 192.168.86.36:5000 because the
browser URL answers 302 when signed out), Home (Home Assistant), Docs (this site; its monitor asks the `docs` container's `/healthz` on the stack network), Security & Identity (Pocket ID, CA install page), Fleet
(Fleet API health, link only). The container resolves the `*.nghodki.ai` names with `extra_hosts` → 192.168.86.11 (the front door VIP) and trusts the web CA through
`NODE_EXTRA_CA_CERTS`.

Add a tile: edit `services.yaml` (no API keys or passwords there), add its host to `extra_hosts` in `compose.yaml`,
PR, `playbooks/ops.yml`. If Pocket ID is down, open the apps directly.
