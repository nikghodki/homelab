---
title: Pocket ID
description: The passkey OIDC provider on dgx-2 (service view). Clients, the sync script and break-glass are on the sign-in page.
---

| | |
|---|---|
| Purpose | One passkey sign-in for every web UI (D22) |
| URL | `https://id.nghodki.ai` (http → https) |
| Host / port | dgx-2, 192.168.86.36:1411 (LAN only; dgx-1's Caddy is the only client) |
| Deploy | `playbooks/console.yml` (stack `console`, `/opt/homelab/console`) |
| Config | env in `hosts/stacks/console/compose.yaml`; contents in `identity/pocket-id.yaml` (applied by `pocketid_sync.py`) |
| Secrets | `secrets/console.enc.yaml` → `pocketid_encryption_key`, `pocketid_static_api_key` (files, 0600, uid 1000), `oidc_<client>_secret` |
| Data | volume `console_pocket-id-data` |
| Health | `https://id.nghodki.ai/healthz` (Homepage). No Gatus check (known gap) |
| Depends on | dgx-1's front door and DNS (clients reach it through 192.168.86.44) |
| k3s target | `console` |

Everything else: [Pocket ID and sign-in](../security/identity.md).
