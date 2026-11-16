---
title: Homepage (ops.nghodki.ai)
description: The launcher at ops.nghodki.ai on the Dell, behind oauth2-proxy and Pocket ID.
---

Homepage is the interim "single pane of glass" launcher until the Fleet Console exists (D23, UI design open).

| | |
|---|---|
| URL | `https://ops.nghodki.ai` (http → https) |
| Host | the Dell, stack `ops` (`hosts/stacks/ops`, `playbooks/ops.yml`, `/opt/homelab/ops`); moved from dgx-2 in PR #55 |
| Containers | `homepage` (`ghcr.io/gethomepage/homepage:v2.8.0`, no ports, `HOMEPAGE_ALLOWED_HOSTS=ops.nghodki.ai`), `oauth2-proxy` (7.15.6) on 192.168.86.49:4180 |
| Sign-in | Pocket ID client `ops`, PKCE S256, `allowed_groups = ["admins"]`, cookie `_ops_oauth2_proxy` for 168 h |
| Secrets | `secrets/console.enc.yaml` → `oidc_ops_secret`, `oauth2_proxy_ops_cookie_secret` |
| Config | `homepage/services.yaml` (tiles), `settings.yaml`, `widgets.yaml` (date and search only), `bookmarks.yaml` (empty) |
| Health | Gatus `ops.nghodki.ai (Homepage)` expects 302 to Pocket ID when signed out |

Tiles (with a `siteMonitor` each, mostly through the front door): Observe (Grafana, Status, Phoenix, ntfy), Models (Open
WebUI, LiteLLM, DGXMM), ML (MLflow; its monitor uses the job API's open `/health` on 192.168.86.36:5000 because the
browser URL answers 302 when signed out), Home (Home Assistant), Docs (this site; its monitor asks the `docs` container's `/healthz` on the stack network), Security & Identity (Pocket ID, CA install page), Fleet
(Fleet API health, link only). The container resolves the `*.nghodki.ai` names with `extra_hosts` → 192.168.86.44 and trusts the web CA through
`NODE_EXTRA_CA_CERTS`.

Add a tile: edit `services.yaml` (no API keys or passwords there), add its host to `extra_hosts` in `compose.yaml`,
PR, `playbooks/ops.yml`. If Pocket ID is down, open the apps directly.
