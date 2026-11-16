---
title: Pocket ID
description: The passkey OIDC provider, in k3s pinned to dgx-2 since 2026-11-16 (service view). Clients, the sync script and break-glass are on the sign-in page.
---

| | |
|---|---|
| Purpose | One passkey sign-in for every web UI (D22) |
| URL | `https://id.nghodki.ai` (http → https) |
| Runs as | k3s since 2026-11-16 (P3.7): `console/pocket-id`, 1 replica, **pinned to dgx-2** (its volume is there), Argo CD app `pocket-id` (`cluster/apps/pocket-id`) |
| Address | fixed ClusterIP `10.43.0.155:1411`; only the front door's Caddy pods may connect (NetworkPolicy). Nothing on the LAN |
| Front door | `id.nghodki.ai` → `10.43.0.155:1411` first, the stopped Docker copy `192.168.86.36:1411` only while the pod's `/healthz` fails, until 2026-11-23 |
| Config | env in `cluster/apps/pocket-id/pocket-id.yaml`; contents in `identity/pocket-id.yaml` (applied by `pocketid_sync.py`, unchanged by the move) |
| Secrets | `secrets/console.enc.yaml` → `pocketid_encryption_key`, `pocketid_static_api_key` (copied byte for byte into the KSOPS Secret `cluster/apps/pocket-id/pocket-id.enc.yaml`), `oidc_<client>_secret` |
| Data | PVC `pocket-id-data` (local-path, 1 Gi) on dgx-2: `pocket-id.db` (SQLite) and `uploads/`. Backed up by restic on dgx-2 since 2026-11-16 (`pocket-id.db` as a SQLite snapshot) |
| Health | `https://id.nghodki.ai/healthz` (Homepage); Gatus `id.nghodki.ai (Pocket ID)` (the discovery document's issuer) |
| Docker copy | `hosts/stacks/console` (`playbooks/console.yml`, which refuses to run without `-e pocketid_docker_rollback=true`): stopped with its data (volume `console_pocket-id-data`) as of the cutover, the rollback until 2026-11-23 |
| Depends on | the front door and DNS in k3s (clients reach it through a Spark's Tailscale IP or the VIP 192.168.86.11); containers with `extra_hosts` go to the VIP 192.168.86.11 |
| Runbook | [`runbooks/sign-in.md`](https://github.com/nikghodki/homelab/blob/main/runbooks/sign-in.md): "Pocket ID in k3s", the move, rollback |

**Moved from Docker on 2026-11-16** (#148, #159): cutover at 15:21, the Docker copy stopped in 0.8 s, its data
(1.1 MB) copied into the PV, the pod Ready at **+6.9 s**. A ~2 Hz probe of `/healthz` and the discovery document
through the door had no failed requests (926); the one in flight on each path was held by Caddy for ~9-10 s. The
hostname, issuer and signing key are unchanged, so passkeys, clients and sessions kept working.

Everything else: [Pocket ID and sign-in](../security/identity.md).
