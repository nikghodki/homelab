# 0002: Backups stay off for now (plan P1.10)

Date: 2026-11-15. Decided by: nikghodki.

**Decision:** the restic setup (#17: rest-server on dgx-2, per-host timers) stays merged but **not deployed**. The off-site
target is also on hold.

**Consequences:**
- Each host still keeps its own data. A disk loss on dgx-1 or the Jetson means rebuilding from Git plus whatever is
  lost. The age key's offline copy is the only off-host secret backup.
- `secrets/backup.enc.yaml` and the roles stay in the repo. Turning backups on is `ansible-playbook playbooks/backups.yml`
  after a `--check --diff`.
