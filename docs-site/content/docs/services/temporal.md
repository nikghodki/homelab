---
title: "Temporal"
description: "Durable workflows on dgx-2: Temporal server, PostgreSQL, admin-tools and the Web UI behind Pocket ID."
---

| | |
|---|---|
| Purpose | Durable workflows for scheduled and long-running jobs (P4.7); later train → eval → export → register → PR for robot policies (P6.6) |
| Host | dgx-2, stack `jobs` (`hosts/stacks/jobs`, `playbooks/jobs.yml`, `/opt/homelab/jobs`) |
| Containers | `temporal` (server 1.32.2, all four services in one), `postgresql` (17.12-alpine, volume `jobs_pg-data`, not published), `admin-tools` (1.32.2: creates/upgrades the `temporal` and `temporal_visibility` schemas, then idles for the CLI), `ui` (2.58.1) |
| Ports | 192.168.86.36:7233 frontend gRPC (LAN only), :8233 UI, :9233 Prometheus metrics |
| URL | `https://temporal.nghodki.ai` (http → https; the UI's cookies are Secure) |
| Sign-in | Temporal UI's own OIDC with Pocket ID client `temporal` (no PKCE: the UI doesn't send it), group `admins`; `TEMPORAL_CORS_ORIGINS=https://temporal.nghodki.ai` |
| Namespace | `homelab`, retention 7 days (created by the playbook if missing) |
| History shards | 4, fixed for the life of the database |
| Dynamic config | `temporal/dynamicconfig.yaml` (`limit.maxIDLength: 255`), polled every 60 s |
| Secrets | `secrets/jobs.enc.yaml` → `postgres_password`; `secrets/console.enc.yaml` → `oidc_temporal_secret` |
| Health | Gatus `Temporal frontend (gRPC)` (tcp 7233), `temporal.nghodki.ai` (`/healthz`); metrics job `temporal` |
| Backups | none (decision 0002): losing dgx-2's disk loses workflow history |
| k3s target | `jobs`, Postgres on CNPG |

## Deploy

`ansible-playbook playbooks/jobs.yml --check --diff`, then for real. The playbook waits until
`temporal operator cluster health` says SERVING and creates the namespace. Upgrades: bump all three Temporal images
together; admin-tools applies schema changes before the server starts.

## Workers

```python
client = await Client.connect("192.168.86.36:7233", namespace="homelab", tls=TLSConfig(...))  # client cert: runbooks/temporal.md
```

**mTLS and per-namespace authorization** since 2026-11-16 (runbooks/temporal.md, "mTLS and authorization"): every
client needs a certificate from the homelab Temporal CA, whose URI SANs name its roles; a small claim mapper in the
server image maps them, Temporal's default authorizer enforces them. Older note, now resolved: add mTLS (and a claim
mapper) before exposing it on Tailscale or off the LAN. No workers exist yet.

## CLI

```bash
ssh nikghodki-dgx-2@192.168.86.36
cd /opt/homelab/jobs
sudo docker compose exec admin-tools temporal operator namespace list
sudo docker compose exec admin-tools temporal workflow list --namespace homelab
```

## Troubleshooting

- `temporal` won't start: it waits for `admin-tools` to be healthy, which waits for the schemas:
  `sudo docker compose logs admin-tools postgresql`.
- UI login loop or "returnUrl not in allowed origins": the CORS origin and the callback
  `https://temporal.nghodki.ai/auth/sso/callback` must match.
- If Pocket ID is down when the UI starts, the UI exits and Docker restarts it until `id.nghodki.ai` answers.
