# 0010: Retire Coolify

- Date: 2026-11-15
- Status: decided (by nikghodki); done the same day

## Context

Coolify 4.7.3 ran on dgx-1 as a hand-run host app (`coolify`, `coolify-db` Postgres 15, `coolify-redis` Redis 7,
`coolify-sentinel`; data in `/data/coolify`), published on 0.0.0.0:8000, :6001 and :6002 and routed as
`coolify.nghodki.ai`. The tool review ([docs/reviews/tool-review-2026-11.md](../docs/reviews/tool-review-2026-11.md)
§2.8) found it hosted **0 applications, 0 services and 0 databases** (its database, read-only). It held the Docker
socket, so it was root-equivalent, and it used ~190 MiB of memory. Argo CD already deploys apps from Git.

## Decision

Retire Coolify completely. Keep nothing: no export of `/data/coolify`, no images, no data.

Removed on 2026-11-15:

- dgx-1: the four containers, the `coolify-db` and `coolify-redis` volumes, the `coolify` Docker network, the images
  `coollabsio/coolify:4.7.3`, `coollabsio/sentinel:1.1.5`, `coollabsio/coolify-helper:1.0.19` and `postgres:15-alpine`
  (only Coolify used it; `redis:7-alpine` stays for LiteLLM), `/data/coolify` (and the then-empty `/data`), Coolify's
  buildx lock files in `/root/.docker/buildx`, and the installer copy in `~/coolify-inspect`.
- Coolify's SSH key (ED25519, comment `coolify`, SHA256:2eNzF4k4fWNPW+LPC7BZT6XOZHUtFZQFsA5KHhElPuk): it was the
  only line in `/root/.ssh/authorized_keys`, so that file is gone. Root login over SSH was already off
  (`PermitRootLogin no`). No other user, sudoers, systemd unit or cron entry was Coolify's. `/etc/docker/daemon.json`
  (nvidia runtime only) was untouched; Coolify hadn't changed it.
- Front door: the `@coolify` site (`/app/*` → :6001, `/terminal/ws` → :6002, the rest → :8000) and both
  `coolify.nghodki.ai` DNS records, in `~/edge-gateway` on dgx-1 and in Git (`cluster/platform/edge`: Caddyfile,
  `names.txt` and the generated CoreDNS zones).
- Docs: the service page and every mention in `docs-site/`, `runbooks/` and `docs/` (design and architecture now say
  retired). There were no Gatus checks, Homepage links, restic paths or AIBOM targets for Coolify.

Memory freed on dgx-1 (`free -m`, before and after): used 8388 → 8243 MiB (145 MiB) and swap 5413 → 5098 MiB;
the containers' working set was ~188 MiB. Disk: ~1.4 GB of images.

## Alternatives considered

- **Keep it, idle.** Rejected: unused, root-equivalent, three LAN-open ports, a Postgres and a Redis to patch.
- **Export `/data/coolify` before removing it** (the review's advice). Rejected by the user: nothing in it was worth
  keeping.

## Consequences

- No PaaS UI. To deploy an app from a repo, add an Argo CD Application (decision 0006).
- Ports 8000, 6001 and 6002 on dgx-1 are free.
- Bringing Coolify back needs a new decision.
