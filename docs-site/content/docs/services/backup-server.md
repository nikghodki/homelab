---
title: Backup server (restic)
description: The append-only restic REST server on the Jetson (500 GB, 3 days kept) and the per-host backup timers.
---

Decision 0002 (revised 2026-11-16): backups are on, every host to the Jetson, 500 GB cap, 3 days kept.
**All backups are on one host: losing the Jetson or its NVMe loses all of them.** There is no off-site copy.

| | |
|---|---|
| Container | `backup-rest-server-1` on the Jetson, `restic/rest-server:0.14.0` (digest-pinned), host network, `mem_limit` 256m, 1 CPU, `cpu_shares` 256 |
| Host / port | Jetson, :8000 (TLS with `backup.crt` from the internal CA; key `pki_backup_key`; SANs `backup.nghodki.ai`, `nikhil-jetson`, `jetson.nghodki.ai`, 192.168.86.211, 100.78.145.123, 127.0.0.1) |
| Who may connect | nftables table `backup_server_guard` (role `backup_server`): only the fleet's LAN addresses (dgx-1, dgx-2, Jetson, Dell, Pi, the Spark VIPs) and loopback; everything else, IPv6 and Tailscale included, is dropped |
| Clients use | `192.168.86.211:8000` (`restic_backup_server`), not a DNS name, so backups don't depend on the front door. `backup.nghodki.ai` points at the Jetson too |
| Options | `--append-only --private-repos`, per-host htpasswd, Prometheus metrics without auth |
| Data | `/srv/homelab-backup/repos/<host>/`: an ext4 filesystem in `/var/lib/homelab-backup.img` (500 GB, allocated up front), loop-mounted (`nofail`). If it isn't mounted, rest-server doesn't start (its bind mount has no fallback) |
| Cap and alert | the 500 GB filesystem is the cap; `FleetDiskWarning` (80 %) and `FleetDiskCritical` (90 %) cover the mount `/srv/homelab-backup` |
| Retention | `homelab-backup-prune.timer` on the Jetson, daily 05:30: `forget --keep-within 3d --prune`, then `check --read-data-subset=5%`; Nice 19, idle I/O, `MemoryMax=1G`. `--keep-within` counts from each host's newest snapshot, so a host that stops backing up keeps its last 3 days |
| Clients | `homelab-backup.timer` on each host, 02:30 + up to 30 min: `restic backup --files-from /etc/restic/paths --exclude-file /etc/restic/excludes --one-file-system` |
| Pre-backup | `/etc/restic/pre-backup.sh`: database dumps (dgx-1: LiteLLM `pg_dump` from the CNPG primary; dgx-2: MLflow and Temporal `pg_dump`s), SQLite online-backup snapshots into `/var/backups/homelab/sqlite/` (DGXMM, Open WebUI, Pocket ID, Grafana, Home Assistant) |
| Secrets | `secrets/backup.enc.yaml` → per host `restic_password_<host>`, `rest_password_<host>`, `rest_password_hash_<host>`; `secrets/pki.enc.yaml` → `pki_backup_key` |
| Deploy | `playbooks/backups.yml`: server play on `backup_server` (the Jetson), the retired dgx-2 server kept off, client play on all hosts |

## Roles

| Role | Does |
|---|---|
| `backup_server` | the 500 GB image file, its ext4 filesystem and loop mount, `repos/`, and the nftables guard (`backup-server-guard.service`) |
| `restic_install` | restic 0.19.1 release binary, checked against `SHA256SUMS`, in `/opt/restic/<version>`, linked to `/usr/local/bin/restic` |
| `restic_backup` | `/etc/restic/env` (repository URL with the host's REST password, repo password), `paths`, `excludes`, the SQLite snapshot helper, `pre-backup.sh`, service and timer; creates the repository on first run |
| `restic_prune` | on the server: per-host password files in `/etc/restic-prune/`, `/usr/local/sbin/homelab-backup-prune`, the daily prune service and timer (clients are append-only, so retention runs here) |

## What each host backs up (`host_vars`)

| Host | Paths |
|---|---|
| dgx-1 | `~/edge-gateway/conf`, `~/edge-gateway/dnsmasq`, `~/voice-assistant/nginx`, `/opt/homelab/litellm` (the stopped Docker copy), a `pg_dump` of CNPG `data/litellm-db`, `~/.defenseclaw`, DGXMM `data`, `config.yaml`, `secrets`, Open WebUI data (minus caches, `gguf`, `hf`), k3s etcd snapshots |
| dgx-2 | `/opt/homelab`, Pocket ID's PV (k3s; `pocket-id.db` as a SQLite snapshot), MLflow and Temporal `pg_dump`s, Grafana's volume (`grafana.db` as a SQLite snapshot), k3s etcd snapshots |
| Jetson | `~/.hermes` (minus checkout, caches, logs), `~/hermes-homes`, Home Assistant config + DB snapshot, `~/.defenseclaw`, `~/.config/livekit`, user units, `~/workspace/roboclaw` |
| Dell | `~/Work`, `~/Documents`, `~/Projects` |
| Pi | `/var/lib/picoclaw`, `/etc/picoclaw`, `~/.picoclaw` (old copy), `~/.defenseclaw`, `~/maps`, `~/workspace`, the Oradar driver source, user units, picoclaw and Edge configs |

Not covered by design: model weights, metrics/logs/traces (Loki, VictoriaMetrics, Tempo, Phoenix), MLflow artifacts, the
CNPG `ops-db` (P3.8), the age key (offline copies only).

## History

The first server ran on dgx-2 (`/srv/homelab-backup`, weekly prune keeping 14 daily, 8 weekly, 12 monthly) from #17
(2026-11-15) until 2026-11-16. Its container is stopped and set not to restart (the container and image are kept), the
prune timer is removed, and its repositories were deleted after the Jetson's first full backup and restore test.
