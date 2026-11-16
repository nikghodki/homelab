---
title: Backups
description: Decision 0002 (revised 2026-11-16): every host backs up nightly to the Jetson, 500 GB cap, 3 days kept. What is protected, the single-host risk, and how to restore.
---

## The decision

Decision 0002, revised 2026-11-16 by the user: backups are **on**. Every host backs up nightly with restic to one
append-only rest-server on the **Jetson** (a 500 GB filesystem on its 4 TB NVMe), and the Jetson keeps **3 days**
(`forget --keep-within 3d --prune`, daily). The old server on dgx-2 is retired and its repositories are deleted.

**The risk, plainly:** all backups now sit on one host. If the Jetson or its NVMe is lost, every backup is lost with
it, and there is no off-site copy. The Jetson's own backup lives on its own disk. And with 3 days kept, anything
noticed later than that can't be restored. This is the user's choice; an off-site copy is still on hold.

## What runs

| Host | `homelab-backup.timer` | Repository |
|---|---|---|
| dgx-1, dgx-2, Jetson, Pi, Dell | enabled, 02:30 + up to 30 min | `rest:https://192.168.86.211:8000/<host>/` |
| Jetson | also `homelab-backup-prune.timer`, daily 05:30 | prunes and checks every repository |

Details: [Backup server](../services/backup-server.md).

## What a backup run protects

The paths in each host's `host_vars` ([Backup server](../services/backup-server.md)), plus database dumps and SQLite
snapshots in `/var/backups/homelab`. All copies are on **the Jetson's disk** (one copy, same house). No off-site copy.

| Protected by the running backups | Not protected |
|---|---|
| dgx-1: front door config, nginx config, LiteLLM's DB dump (from the CNPG primary in k3s) and the stopped Docker copy's config, DefenseClaw, DGXMM data/config/secrets, Open WebUI DB, k3s etcd snapshots | Docker volumes on dgx-2: Loki, VictoriaMetrics, MLflow artifacts, Phoenix, Alertmanager (silences) |
| dgx-2: `/opt/homelab` (stack configs, rendered secrets); Pocket ID's PV in k3s, `pocket-id.db` as a SQLite snapshot (since 2026-11-16); `pg_dump`s of MLflow (`mlflow-db.sql.gz`) and Temporal (`temporal-db.sql.gz`, `temporal-visibility-db.sql.gz`); Grafana's volume with `grafana.db` as a SQLite snapshot; k3s etcd snapshots (all since 2026-11-16) | the CNPG `ops-db` (P3.8) |
| Jetson: Hermes state, HA config + DB snapshot, DefenseClaw, LiveKit config, roboclaw | model weights (re-downloadable) |
| Pi: picoclaw, DefenseClaw, maps, workspace, units | the Dell |

## Checking it

- Last runs: `journalctl -t homelab-backup --since -1d` on a host; prune: `journalctl -t homelab-backup-prune` on the Jetson.
- Space: `df -h /srv/homelab-backup` on the Jetson (alerts at 80 and 90 %).
- There is no alert yet for a failed or missing nightly run (the journal has `SyslogIdentifier=homelab-backup`).

## Restoring a database dump or snapshot

On the host, as root, with `/etc/restic/env` loaded (`set -a; . /etc/restic/env; set +a`):

```bash
restic restore latest --include /var/backups/homelab/temporal-db.sql.gz --target /tmp/restore
# Postgres: into a scratch database first, e.g.
gunzip -c /tmp/restore/var/backups/homelab/temporal-db.sql.gz | docker exec -i jobs-postgresql-1 psql -U temporal -d scratch
# SQLite snapshots: /var/backups/homelab/sqlite/<name>.sqlite3, copy over the stopped service's file
```

## Other copies that exist

- The age key: password manager + paper.
- k3s etcd snapshots: local on each server, twice a day, 5 kept (dgx-1's and dgx-2's are also in the backups).
- The Pi's pre-migration backup: `~/backups/nikraspberry-2026-11-14/pi-full.tar.zst` on dgx-1 (P0.1).
- Git: everything in the repo.
