---
title: Coolify
description: The self-hosted PaaS on dgx-1 (a host app outside the repo).
---

| | |
|---|---|
| Containers | `coolify` (`coollabsio/coolify:4.7.3`), `coolify-db` (postgres 15), `coolify-redis` (redis 7), `coolify-sentinel` |
| Host / ports | dgx-1: 0.0.0.0:8000 → 8080 (web), :6001 (soketi realtime), :6002 (web terminal) |
| URL | `https://coolify.nghodki.ai`: `/app/*` → 100.65.137.82:6001, `/terminal/ws` → :6002, the rest → :8000 (no buffering) |
| Sign-in | Coolify's own login (not behind Pocket ID: own login and API clients) |
| Managed by | Coolify itself; not in this repo, not in Ansible |
| Health | none in Gatus |
| Plan | stays a host app (architecture §3.3) |

Coolify's own proxy must stay off (`None`): ports 80/443 on dgx-1 belong to edge-caddy (unverified in the repo; this
is the operator's standing note).

Family and guests can reach `coolify.nghodki.ai` through the front door over Tailscale; Coolify's login is the gate.
