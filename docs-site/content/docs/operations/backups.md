---
title: Backups
description: What decision 0002 says (backups off), what is actually running (backups on), what is and isn't protected, and how to turn backups on or off properly.
---

## The decision

Decision 0002 (2026-11-15): the restic setup from PR #17 stays merged but **not deployed**; the off-site target is on
hold. Consequence written there: each host keeps its own data; a disk loss on dgx-1 or the Jetson means rebuilding from
Git plus whatever is lost; the age key's offline copy is the only off-host secret backup.

## What is actually running (checked 2026-11-15)

| Host | `homelab-backup.timer` | Last run |
|---|---|---|
| dgx-1 | enabled, next 02:30 + jitter | 03:24 on 2026-11-15, snapshot saved |
| dgx-2 | enabled; also `homelab-backup-prune.timer` (Sunday 05:00) | 03:24 on 2026-11-15 (result not checked) |
| Jetson | enabled | never yet |
| Pi | enabled | never yet |
| Dell | not installed | — |

And the rest-server (`backup-rest-server-1`) runs on dgx-2. So backups **are on** for four hosts, to dgx-2. This is a
real conflict between the decision and the live state ([discrepancies](../decisions/discrepancies.md)). Nothing was
changed while writing these docs.

## What a backup run protects

The paths in each host's `host_vars` ([Backup server](../services/backup-server.md)), plus database dumps and SQLite
snapshots in `/var/backups/homelab`. All copies are on **dgx-2's disk** (one copy, same house). No off-site copy.

| Protected by the running backups | Not protected |
|---|---|
| dgx-1: front door config, nginx config, LiteLLM's DB dump (from the CNPG primary in k3s) and the stopped Docker copy's config, DefenseClaw, DGXMM data/config/secrets, Open WebUI DB, k3s etcd snapshots | Docker volumes on dgx-2: Loki, VictoriaMetrics, MLflow artifacts, Phoenix, Alertmanager (silences) |
| dgx-2: `/opt/homelab` (stack configs, rendered secrets); Pocket ID's PV in k3s, `pocket-id.db` as a SQLite snapshot (since 2026-11-16); `pg_dump`s of MLflow (`mlflow-db.sql.gz`) and Temporal (`temporal-db.sql.gz`, `temporal-visibility-db.sql.gz`); Grafana's volume with `grafana.db` as a SQLite snapshot; k3s etcd snapshots (all since 2026-11-16) | the CNPG `ops-db` (P3.8) |
| Jetson: Hermes state, HA config + DB snapshot, DefenseClaw, LiveKit config, roboclaw | model weights (re-downloadable) |
| Pi: picoclaw, DefenseClaw, maps, workspace, units | the Dell |

## Turning backups off (to match the decision)

Your call. One way (from dgx-1, nothing in the repo changes):

```bash
for h in dgx-1 dgx-2 jetson pi; do
  ~/.venvs/ansible/bin/ansible $h -b -m systemd_service -a "name=homelab-backup.timer enabled=false state=stopped"
done
~/.venvs/ansible/bin/ansible dgx-2 -b -m systemd_service -a "name=homelab-backup-prune.timer enabled=false state=stopped"
# and stop the server: sudo docker compose --project-directory /opt/homelab/backup down (on dgx-2)
```

Then record it in decision 0002 (or a new decision).

## Turning backups on (properly)

1. Replace decision 0002 with a new decision (target, retention, off-site or not).
2. `ansible-playbook playbooks/backups.yml --check --diff`, then for real. Add the Dell if wanted.
3. Do a restore test (`restic -r ... restore latest --target /tmp/restore-test` on a host, using `/etc/restic/env`).
4. Add an alert: there is none today for a failed or missing backup (the journal has `SyslogIdentifier=homelab-backup`).
5. Temporal, MLflow, Grafana and etcd snapshots are in since 2026-11-16 (dumps in `restic_backup_pre_commands`).

## Restoring a database dump or snapshot

On the host, as root, with `/etc/restic/env` loaded (`set -a; . /etc/restic/env; set +a`):

```bash
restic restore latest --host dgx-2 --include /var/backups/homelab/temporal-db.sql.gz --target /tmp/restore
# Postgres: into a scratch database first, e.g.
gunzip -c /tmp/restore/var/backups/homelab/temporal-db.sql.gz | docker exec -i jobs-postgresql-1 psql -U temporal -d scratch
# SQLite snapshots: /var/backups/homelab/sqlite/<name>.sqlite3, copy over the stopped service's file
```

## Other copies that exist

- The age key: password manager + paper.
- k3s etcd snapshots: local on each server, twice a day, 5 kept.
- The Pi's pre-migration backup: `~/backups/nikraspberry-2026-11-14/pi-full.tar.zst` on dgx-1 (P0.1).
- Git: everything in the repo.
