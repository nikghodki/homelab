---
title: Open WebUI
description: "Ask Me", the chat UI for people (including family), backed by LiteLLM and (admins only) the Hermes agent; in k3s on dgx-1 since 2026-11-16.
---

| | |
|---|---|
| Runs as | k3s pod `open-webui/open-webui` on dgx-1 (Argo CD app `open-webui`, `cluster/apps/open-webui`), `ghcr.io/nikghodki/open-webui:v0.13.3-askme.1` by digest (upstream plus the Ask Me patch), read-only root, no capabilities, limits 2 CPU / 3 Gi |
| Address | fixed ClusterIP `10.43.0.130:8080`; nothing published on the LAN |
| URL | `https://webui.nghodki.ai` (front door; 30 min timeouts for streaming) |
| Sign-in | Open WebUI's own accounts, including family accounts. Pocket ID after the family list (P1.13) |
| Data | PVC `open-webui-data` (local-path on dgx-1): `webui.db`, the built-in Chroma DB, the embedding-model cache. The pod refuses to start on an empty volume |
| Models | **Ask Me — direct (qwen3.8-27b)** (default, everyone) through LiteLLM `http://10.43.0.150:4000/v1`; **Ask Me — Hermes agent** (admins only) through Hermes on the Jetson `:8642`. Stored in Open WebUI's database, set from Git by the PostSync Job `open-webui-config` (`runbooks/open-webui.md`, "Config from Git") |
| TPS | global filter `tps_meter`: live tok/s while streaming, then tok/s, tokens, first-token time, total |
| Network policy | in: the front door's Caddy pods and the config Job; out: DNS, LiteLLM, Hermes (Jetson :8642), internet HTTP/S |
| Backups | its SQLite DB is snapshotted before each restic run on dgx-1 (`restic_backup_sqlite`, the PV path) |
| Health | Gatus `webui.nghodki.ai`; Homepage monitor `/health`; probes on `/health` |
| AIBOM | the nightly scan still names the Docker container `open-webui` (stopped; observability session) |
| Runbook | [`runbooks/open-webui.md`](https://github.com/nikghodki/homelab/blob/main/runbooks/open-webui.md): data, the move, rollback, upgrades |

**Moved from Docker on 2026-11-16** (P3.7, PRs #124, #127). The old container `open-webui` (`~/open-webui`, volume
`open-webui_open-webui-data`) is **stopped, kept until 2026-11-23** as the rollback; until then Caddy falls back to it
on `100.65.137.82:3100` whenever the pod's health check fails.

Family and guests reach it over Tailscale (grant 2) through the front door. After changes, check from a family device
that it still opens (Tailscale policy procedure).
