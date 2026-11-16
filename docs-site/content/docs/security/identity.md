---
title: "Pocket ID and sign-in"
description: "One passkey sign-in for every web UI: Pocket ID, its groups and OIDC clients, the sync script, the edge-auth sign-in for apps without a login, and break-glass."
---

Pocket ID (D22) is a passkey-only OIDC provider; no passwords. Apps with their own OIDC are one sign-in each; the apps
without a login share one sign-in at the front door (`edge-auth`).

| | |
|---|---|
| Version | Pocket ID 2.19.3 (`ghcr.io/pocket-id/pocket-id`, digest-pinned) |
| Host | k3s since 2026-11-16: `console/pocket-id` (Argo CD app `pocket-id`, `cluster/apps/pocket-id`), pinned to dgx-2. The Docker stack `console` (`hosts/stacks/console`, `playbooks/console.yml`) is stopped, the rollback until 2026-11-23 |
| Address | fixed ClusterIP `10.43.0.155:1411`; only the front door's Caddy pods may connect |
| URL | `https://id.nghodki.ai` (http redirects: passkeys need HTTPS) |
| Data | PVC `pocket-id-data` (local-path on dgx-2, SQLite). In restic on dgx-2 since 2026-11-16 (a SQLite snapshot of `pocket-id.db`) |
| Secrets | `secrets/console.enc.yaml` → `pocketid_encryption_key`, `pocketid_static_api_key`, copied byte for byte into the KSOPS Secret `cluster/apps/pocket-id/pocket-id.enc.yaml` (mounted as files, uid 1000) |
| Settings | `APP_URL=https://id.nghodki.ai`, `TRUST_PROXY=true`, analytics and version check off |
| Health | `https://id.nghodki.ai/healthz` (Homepage monitor) |
| Contents in Git | `identity/pocket-id.yaml`, applied by `hosts/files/pocket-id/pocketid_sync.py` |

## Groups, users, clients (`identity/pocket-id.yaml`)

Groups: `admins`, `family`. Users: `nikghodki` (admin, in `admins`). Nobody is in `family` yet.

| Client | Callback | PKCE | Allowed group | App side |
|---|---|---|---|---|
| `grafana` | `https://grafana.nghodki.ai/login/generic_oauth` | yes | admins | Grafana generic OAuth; `admins` → GrafanaAdmin, else Viewer (strict) |
| `phoenix` | `https://phoenix.nghodki.ai/oauth2/pocketid/tokens` | yes | admins | `PHOENIX_OAUTH2_POCKETID_*`; scope `groups` must be requested; `admins` → ADMIN |
| `edge-auth` | `https://auth.nghodki.ai/oauth2/callback` | yes (S256) | admins | `edge/edge-auth` (oauth2-proxy in k3s) for Homepage, docs, Gatus' status page, MLflow; each route also checks its group |
| `temporal` | `https://temporal.nghodki.ai/auth/sso/callback` | **no** (Temporal UI 2.58 doesn't send it) | admins | Temporal UI's own OIDC |
| `argocd` | `https://argocd.nghodki.ai/auth/callback` | yes (S256) | admins | Argo CD OIDC; RBAC `g, admins, role:admin`, no default role |
| `litellm` | `https://litellm-admin.nghodki.ai/sso/callback` | yes (S256) | admins | LiteLLM generic OIDC SSO; `admins` → `proxy_admin` (tied to the existing admin user by email), anyone else `internal_user_viewer` |

Every client with an allowed group is group-restricted (`isGroupRestricted`; Pocket ID 2.x doesn't enforce the
allowed groups without it). Client secrets are `oidc_<client>_secret` in `secrets/console.enc.yaml`. The Argo CD one is also copied to
`cluster/platform/argocd/extras/oidc.enc.yaml`.

## The sync script

`pocketid_sync.py` makes Pocket ID match the YAML (groups, users, clients, including callback and logout callback
URLs). It is idempotent, writes new client secrets straight into SOPS (on `sops set --value-stdin`, so they never show
in `ps` or a log), and uses the static API key from SOPS. Tests in
`hosts/files/pocket-id/tests/` run in CI.

```bash
# on dgx-1, in ~/homelab
source ~/.venvs/ansible/bin/activate
python hosts/files/pocket-id/pocketid_sync.py --dry-run
python hosts/files/pocket-id/pocketid_sync.py
python hosts/files/pocket-id/pocketid_sync.py --login-link <username>   # one-time link, 1 hour, to add a passkey
```

Env: `POCKETID_URL` (default `https://id.nghodki.ai`). The host must trust the web CA (it does, via `homelab_ca`).

## Add a person or a passkey

1. Add the user to `identity/pocket-id.yaml` (and a group), PR, merge, run the sync.
2. Send them the link from `--login-link`. They open it on a device that trusts the web CA and add a passkey.
3. Ask for a second passkey on another device as a backup.

## Add an app

**If it speaks OIDC:** add a client to the YAML, sync, wire the secret into the app (`compose_stack_env` or a
template), redeploy its stack. Containers that talk to Pocket ID need
`extra_hosts: ["id.nghodki.ai:192.168.86.11"]` (the front door's VIP) and the host CA bundle mounted at `/etc/ssl/certs/ca-certificates.crt`.

**If it has no login: one block in the front door's Caddyfile** ([decision 0011](https://github.com/nikghodki/homelab/blob/main/decisions/0011-one-sign-in-proxy.md)).
One oauth2-proxy, `edge/edge-auth` in k3s (2 replicas, one per Spark), signs people in for every such app with one
Pocket ID client (`edge-auth`) and one callback (`https://auth.nghodki.ai/oauth2/callback`). Its cookie `_edge_auth`
is for `.nghodki.ai` (Secure, HttpOnly, 7 days, refreshed hourly), so **one sign-in opens Homepage, the docs, Gatus'
status page and MLflow**.

1. Put a token gate in front of the app on its host: a Caddy site on the host's LAN IP that passes only requests with
   the front door's `X-Edge-Origin` token (`edge_origin_token`) and answers 403 otherwise (examples: the ops stack's
   `docs/Caddyfile.j2`, `alerting/status-gate/Caddyfile.j2`). The app itself gets no `ports:`.
2. In `cluster/platform/edge/caddy/Caddyfile`:
   ```caddyfile
   @<app> host <app>.nghodki.ai
   handle @<app> {
   	import signed_in <LAN IP>:<gate port> admins
   }
   ```
   The last word is the Pocket ID group the route requires. No Pocket ID change for a new app.
3. Check: `.github/scripts/verify-edge-auth.sh`: signed out, 302 to `https://id.nghodki.ai/authorize?...client_id=edge-auth...`;
   the gate answers 403 without the door.

Full recipe, rotation and troubleshooting: `runbooks/sign-in.md`.

## Not on Pocket ID, and why

| App | Why |
|---|---|
| Home Assistant | Its phone app can't sign in through a forward-auth proxy. HA keeps its own login (trusted proxies set, P0.16) |
| Open WebUI | Has family accounts to migrate |
| ntfy | Own logins or phone apps; a proxy would break the phone apps and API clients. (The voice agent, also listed here before, was retired in D26) |
| Fleet API | Machine token auth, not people |

## Break-glass (Pocket ID down)

| App | How |
|---|---|
| Grafana | local `admin` login; password `grafana_admin_password` in `secrets/observe.enc.yaml` |
| Phoenix | default admin; `phoenix_admin_password` in `secrets/observe.enc.yaml` |
| Gatus | no login of its own; checks keep running. UI: `ssh -L 8082:127.0.0.1:8082 nikghodki@192.168.86.49`, open `http://localhost:8082` |
| Homepage | it's only a launcher: open the apps directly (URLs in `hosts/stacks/ops/homepage/services.yaml`) |
| Argo CD | `argocd --core --kube-context argocd ...` on dgx-1 needs no login; for the UI, temporarily enable local admin (runbooks/argocd.md) |
| Temporal UI | the CLI: `sudo docker compose exec admin-tools temporal ...` on dgx-2. The UI exits and restarts until Pocket ID is back |
| MLflow | job API on 192.168.86.36:5000 with basic auth (`mlflow_api_password`) |
| LiteLLM admin UI | on dgx-1 `kubectl -n litellm port-forward svc/litellm 4000:4000`, plus `ssh -L 4000:127.0.0.1:4000 nikghodki-dgx@<dgx-1>`, open `http://localhost:4000/fallback/login`, user `nikghodki`, password `litellm_ui_password` in `secrets/litellm.enc.yaml` (the master key works too) |

## Gotchas

- Gatus' own `security.oidc` panics at start when Pocket ID is unreachable, which would stop all checks exactly when
  the Sparks are down. That's why Gatus' UI is signed in at the front door instead (its checks don't go through it).
- Phoenix answers "authentication failed" unless the client requests the `groups` scope (PR #36).
- Pocket ID is pinned to dgx-2 (its volume) and is reached through the front door (either Spark): dgx-2 down breaks sign-in.
- Retired clients (`ops`, `docs`, `gatus`, `mlflow`, replaced by `edge-auth`) are listed under `removedClients`; the
  sync deletes them in Pocket ID and drops their secrets.
