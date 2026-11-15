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
| Gatus (status page) | `security.oidc` (no PKCE: Gatus 5.38 doesn't send it) | admins |
| Phoenix | `PHOENIX_OAUTH2_POCKETID_*` (PKCE); `admins` → ADMIN | admins |

Containers that talk to Pocket ID get `extra_hosts: id.nghodki.ai:192.168.86.44` and the host's CA bundle, which includes the
web CA.

Break-glass: the Grafana `admin` and Phoenix default-admin passwords (in `secrets/observe.enc.yaml`) still work. Gatus has no
local login: if Pocket ID is down, remove `security:` from its config and redeploy.

## Not on Pocket ID yet, and why

- **Home Assistant:** its phone app can't sign in through a forward-auth proxy. HA keeps its own login (and needs its
  trusted proxies set, P0.16).
- **LiteLLM UI, DGXMM UI, Open WebUI:** wait for the DGXMM session (LiteLLM and DGXMM are being changed there).
  Open WebUI has family accounts to migrate.
- **ntfy, Coolify, voice-agent:** their own logins or phone apps. Revisit with oauth2-proxy if needed.
