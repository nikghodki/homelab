# Sign-in with Pocket ID (plan P1.13, D22)

| Piece | Where |
|---|---|
| Pocket ID 2.19.2 | dgx-2, `hosts/stacks/console` (`playbooks/console.yml`), LAN port 1411 |
| `https://id.nghodki.ai` | dgx-1 front door (`~/edge-gateway/conf/Caddyfile`, `@id`); http is redirected because passkeys need HTTPS |
| Groups, users, OIDC clients | `identity/pocket-id.yaml`, applied by `hosts/files/pocket-id/pocketid_sync.py` |
| Secrets | `secrets/console.enc.yaml`: encryption key, static API key, `oidc_<client>_secret` |

## Change users or clients

Edit `identity/pocket-id.yaml`, then run this on dgx-1:

```bash
source ~/.venvs/ansible/bin/activate
python hosts/files/pocket-id/pocketid_sync.py --dry-run
python hosts/files/pocket-id/pocketid_sync.py
```

New client secrets go straight into SOPS. Commit `secrets/console.enc.yaml` with the change, then wire the app
(`compose_stack_env` or a template) and redeploy its stack.

## Add a person or a new passkey

Add the user to the YAML and sync, then send them the link from
`pocketid_sync.py --login-link <username>`. It's single use and valid for 1 hour. They open it on a device that trusts the
homelab web CA (`http://ca.nghodki.ai`) and add a passkey. Ask for a second passkey on another device as a backup.

## Apps

| App | How | Who |
|---|---|---|
| Grafana | Generic OAuth (PKCE); `admins` group → Grafana Admin | admins |
| Gatus (status page) | oauth2-proxy in front (`status-proxy` in `hosts/stacks/alerting` on the Dell; client `gatus`, no PKCE, `proxy_prefix = /authorization-code` to keep the client's callback). Not Gatus' own `security.oidc`: it panics at start when Pocket ID is unreachable, which would stop the checks during a Spark outage | admins |
| Phoenix | `PHOENIX_OAUTH2_POCKETID_*` (PKCE); `admins` → ADMIN. Needs `..._SCOPES: groups`, or Pocket ID sends no groups claim and Phoenix answers "authentication failed" | admins |
| Homepage (`https://ops.nghodki.ai`) | oauth2-proxy in front (client `ops`, PKCE S256, `--allowed-group=admins`); Homepage itself has no login. Runs on the Dell (`hosts/stacks/ops`, `playbooks/ops.yml`), LAN port 4180 | admins |
| MLflow (`https://mlflow.nghodki.ai`) | oauth2-proxy in front (client `mlflow`, same recipe, `hosts/stacks/ml`); jobs use a separate basic-auth API port ([mlflow.md](mlflow.md)) | admins |

Containers that talk to Pocket ID get `extra_hosts: id.nghodki.ai:192.168.86.44` and the host's CA bundle, which includes the
web CA.

## Apps without their own login: oauth2-proxy

Homepage (`hosts/stacks/ops`, on the Dell) is the first app behind oauth2-proxy 7.15. The pattern for the next one:

1. Add an OIDC client to `identity/pocket-id.yaml` with callback `https://<app>.nghodki.ai/oauth2/callback` and
   `groups: [admins]` (or whoever), then sync. The secret lands in SOPS as `oidc_<client>_secret`.
2. Add a cookie secret to the stack's SOPS file (32 random bytes, base64url), e.g.
   `oauth2_proxy_<client>_cookie_secret`.
3. Run an oauth2-proxy container next to the app, configured from a private template like
   `hosts/stacks/ops/oauth2-proxy/oauth2-proxy.cfg.j2` (rendered 0600 for uid 65532): provider `oidc`, issuer
   `https://id.nghodki.ai`, `code_challenge_method = "S256"`, scope `openid email profile groups`,
   `oidc_groups_claim = "groups"`, `allowed_groups`, `email_domains = ["*"]`, `reverse_proxy = true` with
   `trusted_proxy_ips = ["192.168.86.44/32"]` (only the front door may set `X-Forwarded-*`), secure cookies scoped to the
   app's host, `skip_provider_button = true`, and `upstreams` pointing at the app on the stack network. Give it
   `extra_hosts: id.nghodki.ai:192.168.86.44` and the host CA bundle.
4. Publish only oauth2-proxy on the LAN (the host's address, e.g. `192.168.86.36:<port>`); the app gets no `ports:`. Point the front-door route at
   oauth2-proxy, with the http → https redirect (the cookie is `Secure`).
5. Signed out, `curl -s -o /dev/null -w "%{http_code} %{redirect_url}" https://<app>.nghodki.ai/` should give a 302 to
   `https://id.nghodki.ai/authorize?...client_id=<client>...`. `/ping` answers 200 without a session.

Two oauth2-proxy instances don't share sessions; each app is a separate sign-in (one passkey tap, no consent screen).

Break-glass: the Grafana `admin` and Phoenix default-admin passwords (in `secrets/observe.enc.yaml`) still work. Gatus has no
login of its own: if Pocket ID is down, its checks and alerts keep running; for the UI, `ssh -L 8082:127.0.0.1:8082 nikghodki@192.168.86.49`
and open `http://localhost:8082`. Homepage has none either; it's only a
launcher, so if Pocket ID is down open the apps directly (URLs in `hosts/stacks/ops/homepage/services.yaml`).

## Not on Pocket ID yet, and why

- **Home Assistant:** its phone app can't sign in through a forward-auth proxy. HA keeps its own login (and needs its
  trusted proxies set, P0.16).
- **LiteLLM UI, DGXMM UI, Open WebUI:** wait for the DGXMM session (LiteLLM and DGXMM are being changed there).
  Open WebUI has family accounts to migrate.
- **ntfy, Coolify, voice-agent:** their own logins or phone apps; oauth2-proxy would break the phone apps and
  API clients (ntfy topics, LiveKit). Use the oauth2-proxy pattern above only for browser-only apps.
- **Fleet API:** token auth for machines, not people; it stays as is (Homepage only links to it).
