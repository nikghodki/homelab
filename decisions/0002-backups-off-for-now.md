# 0002: Backups on, to the Jetson, 500 GB, 3 days (plan P1.10)

Date: 2026-11-15, revised 2026-11-16. Decided by: nikghodki.

**Decision (2026-11-16, replaces the first version):** backups are **on**. Every host backs up nightly with restic to
one append-only rest-server on the **Jetson**, on a dedicated **500 GB** filesystem on its 4 TB NVMe. Retention is
**3 days**: the Jetson runs `restic forget --keep-within 3d --prune` daily, and nothing older is kept. The old server
on dgx-2 is retired and its repositories are deleted. The user's words: "there is 4TB disk space on jetson, use cap of
500GB and store all backup on jetson, keep only 3 days backup, purge any backup before that."

**First version (2026-11-15, superseded):** the restic setup (#17: rest-server on dgx-2, per-host timers) stays merged
but not deployed, and the off-site target is on hold. In fact it had been deployed and kept running.

**Consequences:**
- **All backups sit on one host.** Losing the Jetson or its NVMe loses every backup at once. There is no off-site or
  second copy (still on hold). The user chose this.
- The Jetson's own backup is on its own disk, so it only covers mistakes (deleted files, bad deploys), not a disk loss.
- 3 days of history: a problem noticed later than that can't be rolled back from backups.
- The 500 GB filesystem is the hard cap. `FleetDiskWarning`/`FleetDiskCritical` fire at 80/90 % of it. When it's full,
  new backups fail; nothing else on the Jetson is affected.
- Clients stay append-only. Only the Jetson's prune, with the repository passwords from `secrets/backup.enc.yaml`, can
  delete data.
- How it runs: docs-site [Backup server](../docs-site/content/docs/services/backup-server.md) and
  [Backups](../docs-site/content/docs/operations/backups.md). Deploy: `ansible-playbook playbooks/backups.yml`.
