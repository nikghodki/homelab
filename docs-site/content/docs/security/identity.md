---
title: "Pocket ID and sign-in"
description: "One passkey sign-in for every web UI: Pocket ID, its groups and OIDC clients, the sync script, the oauth2-proxy pattern, and break-glass."
---

Pocket ID (D22) is a passkey-only OIDC provider. One person signs in once per app with a passkey; no passwords.

| | |
|---|---|
| Version | Pocket ID 2.19.2 (`ghcr.io/pocket-id/pocket-id`, digest-pinned) |
| Host | dgx-2, stack `console` (`hosts/stacks/console`, `playbooks/console.yml`), `/opt/homelab/console` |
| Port | 192.168.86.36:1411 (LAN only; dgx-1's Caddy is the only client) |
| URL | `https://id.nghodki.ai` (http redirects: passkeys need HTTPS) |
| Data | Docker volume `pocket-id-data` (SQLite). Not backed up by decision 0002 |
| Secrets | `secrets/console.enc.yaml` → `pocketid_encryption_key`, `pocketid_static_api_key` (rendered as files, 0600, uid 1000) |
| Settings | `APP_URL=https://id.nghodki.ai`, `TRUST_PROXY=true`, analytics and version check off |
| Health | `https://id.nghodki.ai/healthz` (Homepage monitor) |
| Contents in Git | `identity/pocket-id.yaml`, applied by `hosts/files/pocket-id/pocketid_sync.py` |

## Groups, users, clients (`identity/pocket-id.yaml`)

Groups: `admins`, `family`. Users: `nikghodki` (admin, in `admins`). Nobody is in `family` yet.

| Client | Callback | PKCE | Allowed group | App side |
|---|---|---|---|---|
| `grafana` | `https://grafana.nghodki.ai/login/generic_oauth` | yes | admins | Grafana generic OAuth; `admins` → GrafanaAdmin, else Viewer (strict) |
| `gatus` | `https://status.nghodki.ai/authorization-code/callback` | **no** (Gatus 5.38 doesn't send it) | admins | oauth2-proxy `status-proxy` on the Dell, `proxy_prefix=/authorization-code` to keep this callback |
| `phoenix` | `https://phoenix.nghodki.ai/oauth2/pocketid/tokens` | yes | admins | `PHOENIX_OAUTH2_POCKETID_*`; scope `groups` must be requested; `admins` → ADMIN |
| `ops` | `https://ops.nghodki.ai/oauth2/callback` | yes (S256) | admins | oauth2-proxy in `hosts/stacks/ops` on the Dell |
| `temporal` | `https://temporal.nghodki.ai/auth/sso/callback` | **no** (Temporal UI 2.58 doesn't send it) | admins | Temporal UI's own OIDC |
| `mlflow` | `https://mlflow.nghodki.ai/oauth2/callback` | yes (S256) | admins | oauth2-proxy in `hosts/stacks/ml` |
| `argocd` | `https://argocd.nghodki.ai/auth/callback` | yes (S256) | admins | Argo CD OIDC; RBAC `g, admins, role:admin`, no default role |

Client secrets are `oidc_<client>_secret` in `secrets/console.enc.yaml`. The Argo CD one is also copied to
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
`extra_hosts: ["id.nghodki.ai:192.168.86.44"]` and the host CA bundle mounted at `/etc/ssl/certs/ca-certificates.crt`.

**If it has no login (oauth2-proxy pattern):**

1. Client with callback `https://<app>.nghodki.ai/oauth2/callback`, `groups: [admins]`; sync.
2. A cookie secret in the stack's SOPS file (32 random bytes, base64url), e.g. `oauth2_proxy_<client>_cookie_secret`.
3. An oauth2-proxy 7.15 container next to the app, from a private template like
   `hosts/stacks/ops/oauth2-proxy/oauth2-proxy.cfg.j2` (rendered 0600 for uid 65532): provider `oidc`, issuer
   `https://id.nghodki.ai`, `code_challenge_method = "S256"`, scope `openid email profile groups`,
   `oidc_groups_claim = "groups"`, `allowed_groups`, `reverse_proxy = true`, `trusted_proxy_ips = ["192.168.86.44/32"]`,
   secure cookies scoped to the app's host, `skip_provider_button = true`, `upstreams` = the app on the stack network.
4. Publish only oauth2-proxy, on the host's LAN address. The app gets no `ports:`.
5. Front-door route to oauth2-proxy with the http → https redirect.
6. Check signed out: `curl -s -o /dev/null -w "%{http_code} %{redirect_url}" https://<app>.nghodki.ai/` gives 302 to
   `https://id.nghodki.ai/authorize?...client_id=<client>...`; `/ping` answers 200.

Two oauth2-proxy instances don't share sessions: each app is its own sign-in (one passkey tap, no consent screen).

## Not on Pocket ID, and why

| App | Why |
|---|---|
| Home Assistant | Its phone app can't sign in through a forward-auth proxy. HA keeps its own login (trusted proxies set, P0.16) |
| LiteLLM UI, DGXMM UI, Open WebUI | Wait for the DGXMM session. Open WebUI has family accounts to migrate |
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

## Gotchas

- Gatus' own `security.oidc` panics at start when Pocket ID is unreachable, which would stop all checks exactly when
  the Sparks are down. That's why Gatus sits behind oauth2-proxy instead.
- Phoenix answers "authentication failed" unless the client requests the `groups` scope (PR #36).
- Pocket ID runs on dgx-2 but is reached through dgx-1's front door: either Spark being down breaks sign-in.
