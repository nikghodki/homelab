---
title: Backup server (restic)
description: The append-only restic REST server on dgx-2 and the per-host backup timers. Decision 0002 says backups are off, but the timers are live.
---

| | |
|---|---|
| Container | `backup-rest-server-1`, `restic/rest-server:0.14.0` (digest-pinned) |
| Host / port | dgx-2, 0.0.0.0:8000 (TLS with `backup.crt` from the internal CA; key `pki_backup_key`) |
| Name | `backup.nghodki.ai` → 192.168.86.36 and 100.124.175.23 |
| Options | `--append-only --private-repos`, per-host htpasswd, Prometheus metrics without auth |
| Data | `/srv/homelab-backup/<host>/` on dgx-2 (root 0700) |
| Prune | `homelab-backup-prune.timer` on dgx-2, Sunday 05:00: `forget --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune`, then `check --read-data-subset=2%` |
| Clients | `homelab-backup.timer` on each host, 02:30 + up to 30 min: `restic backup --files-from /etc/restic/paths --exclude-file /etc/restic/excludes --one-file-system` |
| Pre-backup | `/etc/restic/pre-backup.sh`: database dumps (dgx-1: LiteLLM `pg_dump`), SQLite online-backup snapshots into `/var/backups/homelab/sqlite/` (DGXMM, Open WebUI, Home Assistant) |
| Secrets | `secrets/backup.enc.yaml` → per host `restic_password_<host>`, `rest_password_<host>`, `rest_password_hash_<host>`; `pki_backup_key` |
| Deploy | `playbooks/backups.yml` (server play on `observe`, client play on all hosts) |
| Tailscale | every fleet tag may reach dgx-2:8000 |

## Roles

| Role | Does |
|---|---|
| `restic_install` | restic 0.19.1 release binary, checked against `SHA256SUMS`, in `/opt/restic/<version>`, linked to `/usr/local/bin/restic` |
| `restic_backup` | `/etc/restic/env` (repository URL with the host's REST password, repo password), `paths`, `excludes`, the SQLite snapshot helper, `pre-backup.sh`, service and timer; creates the repository on first run |
| `restic_prune` | on the server: per-host password files in `/etc/restic-prune/`, `/usr/local/sbin/homelab-backup-prune`, the weekly prune service and timer (clients are append-only, so retention runs here) |

## What each host backs up (`host_vars`)

| Host | Paths |
|---|---|
| dgx-1 | `~/edge-gateway/conf`, `~/edge-gateway/dnsmasq`, `~/voice-assistant/nginx`, `~/litellm-setup`, `~/.defenseclaw`, DGXMM `data`, `config.yaml`, `secrets`, Open WebUI data (minus caches, `gguf`, `hf`) |
| dgx-2 | `/opt/homelab` |
| Jetson | `~/.hermes` (minus checkout, caches, logs), `~/hermes-homes`, Home Assistant config, `~/.defenseclaw`, `~/.config/livekit`, user units, `~/workspace/roboclaw` |
| Dell | `~/Work`, `~/Documents`, `~/Projects` |
| Pi | `/var/lib/picoclaw`, `/etc/picoclaw`, `~/.picoclaw` (old copy), `~/.defenseclaw`, `~/maps`, `~/workspace`, the Oradar driver source, user units, picoclaw and Edge configs |

Not covered by design: model weights, metrics/logs/traces, Docker volumes on dgx-2 other than `/opt/homelab` (so
Postgres data in Docker volumes, Grafana, Pocket ID are **not** included), the age key (offline copies only).

## The status conflict

Decision 0002 (2026-11-15) says the restic setup "stays merged but **not deployed**". On the live hosts it **is**
deployed: the rest-server runs on dgx-2, `homelab-backup.timer` is enabled on dgx-1, dgx-2, the Jetson and the Pi, and
dgx-1's run at 03:24 on 2026-11-15 saved a snapshot. The playbook was applied when PR #17 merged (03:07), before the
decision (11:29), and nothing was turned off afterwards. See [Backups](../operations/backups.md) for what to do; it is the
user's call.
