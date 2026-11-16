# Sign-in with Pocket ID (plan P1.13, D22)

| Piece | Where |
|---|---|
| Pocket ID 2.19.3 | k3s, `cluster/apps/pocket-id` (Argo CD app `pocket-id`, namespace `console`), pinned to dgx-2, fixed ClusterIP `10.43.0.155:1411` ([below](#pocket-id-in-k3s)). Until 2026-11-23 the stopped Docker copy on dgx-2 (`hosts/stacks/console`, LAN port 1411) is the fallback |
| `https://id.nghodki.ai` | the front door (`cluster/platform/edge/caddy/Caddyfile`, `@id`); http is redirected because passkeys need HTTPS |
| Sign-in for apps without their own login | `edge/edge-auth` (oauth2-proxy, client `edge-auth`, callback `https://auth.nghodki.ai`), called by the front door: [below](#apps-without-their-own-login-one-block-in-the-caddyfile), [decision 0011](../decisions/0011-one-sign-in-proxy.md) |
| Groups, users, OIDC clients | `identity/pocket-id.yaml`, applied by `hosts/files/pocket-id/pocketid_sync.py`. A client with `groups` gets `isGroupRestricted` (Pocket ID 2.x ignores the allowed groups without it; set on every client on 2026-11-16) |
| Secrets | `secrets/console.enc.yaml`: encryption key, static API key, `oidc_<client>_secret`, `edge_origin_token`; `cluster/platform/edge/edge-auth.enc.yaml` (KSOPS): edge-auth's client secret, cookie secret, origin token |

## Pocket ID in k3s

| | |
|---|---|
| Pod | `console/pocket-id`, 1 replica, **pinned to dgx-2** (its data is on that disk), `Recreate`; uid/gid 1000 (as in Docker), no capabilities, read-only root |
| Image | `ghcr.io/pocket-id/pocket-id:v2.19.3` by digest (allowed in `policies/kyverno/restrict-registries.yaml`) |
| Data | PVC `pocket-id-data` (local-path, 1 Gi) on dgx-2: `pocket-id.db` (SQLite: users, passkeys, OIDC clients, sessions, signing keys) and `uploads/` |
| Secrets | KSOPS `cluster/apps/pocket-id/pocket-id.enc.yaml`: `encryption_key`, `static_api_key`, byte for byte as Ansible rendered them (with the trailing newline) from `pocketid_encryption_key` / `pocketid_static_api_key` in `secrets/console.enc.yaml`. A changed encryption key makes the stored data unreadable |
| Front door | `id.nghodki.ai` → `10.43.0.155:1411` first, the Docker copy `192.168.86.36:1411` while the pod's `/healthz` fails (`lb_policy first`) |
| Network policy | in: only the edge Caddy pods; out: DNS and HTTPS to the internet |
| Guard | init container `data-present`: never starts without `pocket-id.db` (a fresh Pocket ID offers its first-run admin setup to whoever opens it) |

The hostname stays `id.nghodki.ai`, so passkeys (bound to the relying party ID) and every OIDC client's issuer and
callbacks are unchanged. `pocketid_sync.py` talks to `https://id.nghodki.ai` and needs no change.

### Move or restore the data

Pocket ID must be stopped while its files are copied (SQLite with a WAL):

```bash
export KUBECONFIG=~/.kube/config
PV=$(kubectl -n console get pvc pocket-id-data -o jsonpath='{.spec.volumeName}')
DST=$(kubectl get pv $PV -o jsonpath='{.spec.local.path}{.spec.hostPath.path}')        # on dgx-2
# from a restic restore or the Docker volume /var/lib/docker/volumes/console_pocket-id-data/_data, on dgx-2:
sudo rsync -aHAX --delete --chown=1000:1000 "$SRC/" "$DST/"
kubectl -n console delete pod -l app.kubernetes.io/name=pocket-id                     # the guard runs again at once
```

Pocket ID refuses to start ("there's already one instance of Pocket ID running") while `francis_hosts` in the
database holds another instance's recent health check. A clean stop removes it; after an unclean one (or on a copy
of a running database), clear it in the copy before starting: `sqlite3 "$DST/pocket-id.db" 'delete from francis_hosts'`,
only when no other Pocket ID uses that file.

## Change users or clients

Edit `identity/pocket-id.yaml`, then run this on dgx-1:

```bash
source ~/.venvs/ansible/bin/activate
python hosts/files/pocket-id/pocketid_sync.py --dry-run
python hosts/files/pocket-id/pocketid_sync.py
```

New client secrets go straight into SOPS. Commit `secrets/console.enc.yaml` with the change, then wire the app
(`compose_stack_env` or a template) and redeploy its stack. To retire a client, move its id from `clients` to
`removedClients`: the sync deletes it in Pocket ID and drops `oidc_<id>_secret` from SOPS (run it after the app stopped
using it, and commit the SOPS file if it changed).

## Add a person or a new passkey

Add the user to the YAML and sync, then send them the link from
`pocketid_sync.py --login-link <username>`. It's single use and valid for 1 hour. They open it on a device that trusts the
homelab web CA (`http://ca.nghodki.ai`) and add a passkey. Ask for a second passkey on another device as a backup.

## Apps

| App | How | Who |
|---|---|---|
| Grafana | Generic OAuth (PKCE); `admins` group → Grafana Admin | admins |
| Phoenix | `PHOENIX_OAUTH2_POCKETID_*` (PKCE); `admins` → ADMIN. Needs `..._SCOPES: groups`, or Pocket ID sends no groups claim and Phoenix answers "authentication failed" | admins |
| Temporal UI | Its own OIDC (client `temporal`, no PKCE) ([temporal.md](temporal.md)) | admins |
| Argo CD (`https://argocd.nghodki.ai`) | Its own OIDC (client `argocd`, PKCE S256, `rootCA` = web CA); `admins` → `role:admin`, no default role; local admin off ([argocd.md](argocd.md)). The client secret is also copied to `cluster/platform/argocd/extras/oidc.enc.yaml` for KSOPS | admins |
| Homepage (`https://ops.nghodki.ai`) | front door sign-in (`edge-auth`); backend: the ops stack's Caddy gate `192.168.86.49:4180` → Homepage (Dell, `hosts/stacks/ops`) | admins |
| Docs (`https://docs.nghodki.ai`) | front door sign-in; backend: the docs Caddy `192.168.86.49:4181` (Dell, `hosts/stacks/ops`, [docs-site.md](docs-site.md)) | admins |
| Gatus status page (`https://status.nghodki.ai`) | front door sign-in (`/health` open); backend: `status-gate` `192.168.86.49:8081` (Dell, `hosts/stacks/alerting`). Not Gatus' own `security.oidc`: it panics at start when Pocket ID is unreachable, which would stop the checks during a Spark outage. The checks never go through the gate | admins |
| MLflow (`https://mlflow.nghodki.ai`) | front door sign-in; backend: the ml stack's Caddy `192.168.86.36:4181` (dgx-2, `hosts/stacks/ml`); jobs use the basic-auth API on :5000 ([mlflow.md](mlflow.md)) | admins |
| DGXMM (`https://dgxmanager.nghodki.ai`) | front door sign-in (`import session_check admins` in a `route`, since DGXMM's proxy needs SSE and its 1 MB limit); DGXMM has no login of its own. `/dgxmm/healthz` is open for the checks. Its backend is on dgx-1's cable address, which only the Caddy pods reach, so it needs no origin token | admins |
| LiteLLM admin UI (`https://litellm-admin.nghodki.ai`) | front door sign-in (`session_check`), then LiteLLM's generic OIDC SSO (client `litellm`, PKCE S256, scope `groups`; `GENERIC_ROLE_MAPPINGS_*`: `admins` → `proxy_admin`). The Pocket ID user is tied to LiteLLM's existing admin user `default_user_id` by email, so no new LiteLLM user is created (SSO stays free below 5 users). Break-glass: `/fallback/login` ([litellm.md](litellm.md#admin-ui-sign-in)). The API on `model.nghodki.ai` stays key-only | admins |

Containers that talk to Pocket ID get `extra_hosts: id.nghodki.ai:<front door>` and the host's CA bundle, which includes
the web CA (`edge-auth` resolves it through kube-dns → edge-dns, like Argo CD, and trusts only the web CA).

## Apps without their own login: one block in the Caddyfile

One oauth2-proxy, **`edge/edge-auth`** (2 replicas, one per Spark; config `cluster/platform/edge/edge-auth/`), signs
people in for every app that has no login of its own ([decision 0011](../decisions/0011-one-sign-in-proxy.md)). One
Pocket ID client (`edge-auth`), one callback (`https://auth.nghodki.ai/oauth2/callback`), one cookie (`_edge_auth`,
`.nghodki.ai`, Secure, 7 days, refreshed hourly): **one sign-in covers every such app**, on the LAN and the tailnet.

No backend receives the sign-in cookies: every `reverse_proxy` in the Caddyfile imports `strip_session_cookie`
(drops `_edge_auth*` from the `Cookie` header), signed-in route or not; only edge-auth's own routes on `auth.nghodki.ai`
and the forward-auth calls keep them (2026-11-16, decision 0011).

**Put an app behind Pocket ID:**

1. Make the app reachable from the Sparks **only through a gate that checks the front door's token**, and publish
   only that gate, on the host's LAN IP (never `0.0.0.0`). Usually the stack already has a Caddy; add a site:
   ```caddyfile
   :<port> {
   	@door header X-Edge-Origin "{{ edge_origin_token }}"   # Ansible: console_secrets.edge_origin_token
   	handle @door {
   		request_header -X-Edge-Origin
   		reverse_proxy <app>:<port>
   	}
   	handle {
   		respond "Use https://<app>.nghodki.ai" 403
   	}
   }
   ```
   Render it as a private template (0600 for the container's uid: `compose_stack_private_templates`) and don't give
   that site an access log (it would record the token). Paths that machines need without a session (health,
   metrics, webhooks) get their own `handle` before `@door`, as in `hosts/stacks/alerting/status-gate/Caddyfile.j2`.
2. One block in `cluster/platform/edge/caddy/Caddyfile` (inside `(nghodki_routes)`), plus the name in `names.txt` if
   it's new (runbooks/edge.md):
   ```caddyfile
   @<app> host <app>.nghodki.ai
   handle @<app> {
   	import signed_in <host LAN IP>:<port> admins
   }
   ```
   The second argument is the Pocket ID group the route requires (`allowed_groups`); a signed-in user outside it
   gets 403. The `edge-auth` client admits only `admins` today: for a family app, add `family` to its `groups` in
   `identity/pocket-id.yaml` and sync, then use `import signed_in ... family`. Nothing else changes in Pocket ID.
3. PR, gated merge; Argo CD rolls Caddy within ~3 minutes; deploy the stack.
4. Check: `.github/scripts/verify-edge-auth.sh` (add the route to its `ROUTES` and the gate to `GATES`): signed out, a
   302 to `https://id.nghodki.ai/authorize?...client_id=edge-auth...`; the gate refuses direct access with 403. Add
   the same two Gatus checks as the existing apps (`ignore-redirect` 302 through the VIP; `... refuses direct access`).

What the snippet does, and why it isn't Caddy's `forward_auth` shortcut: decision 0011. Sign out:
`https://auth.nghodki.ai/oauth2/sign_out`.

**If an app needs to know who is signed in**, add `X-Auth-Request-User`/`-Email`/`-Groups` to the `@ok`
`handle_response` in the snippet (`request_header X-Auth-Request-Email {rp.header.X-Auth-Request-Email}`) and strip
client-supplied copies first; none of today's apps uses them.

**Rotate:**

- Cookie secret (signs everyone out): new 32 random bytes (base64url) in `cluster/platform/edge/edge-auth.enc.yaml`
  (`cookie-secret`), merge, `kubectl -n edge rollout restart deploy/edge-auth`.
- Client secret: Pocket ID UI → OIDC clients → edge-auth → new secret; put it in `oidc_edge-auth_secret`
  (`sops set --value-stdin`) and `client-secret` in `edge-auth.enc.yaml`; merge; restart `edge-auth`.
- Edge origin token: new `secrets.token_urlsafe(32)` in `edge_origin_token` and `origin-token`; merge; restart
  `edge-caddy`, then redeploy `ops.yml`, `alerting.yml`, `ml.yml` (each gate 403s from the restart until its stack
  is redeployed).

Never print them: build the Secret as in runbooks/edge.md "Renew the wildcard cert" (decrypt to a pipe, re-encrypt).

**When it breaks:**

- Every signed-in app answers 502: `edge-auth` is down (`kubectl -n edge get pods -l app.kubernetes.io/name=edge-auth`,
  `kubectl -n edge logs deploy/edge-auth`). The apps fail closed; Gatus' checks keep running.
- 403 "Use https://..." from the app: the request reached the gate without the token (Caddy's `EDGE_ORIGIN_TOKEN`
  and the stack's rendered Caddyfile differ: redeploy the stack, or restart `edge-caddy` after a Secret change).
- A sign-in loop or "CSRF cookie not found": the browser blocks the `.nghodki.ai` cookie, or the clock is off; clear
  `_edge_auth*` cookies.

Break-glass: the Grafana `admin` and Phoenix default-admin passwords (in `secrets/observe.enc.yaml`) still work. Gatus has no
login of its own: if Pocket ID or the Sparks are down, its checks and alerts keep running; for the UI,
`ssh -L 8082:127.0.0.1:8082 nikghodki@192.168.86.49` and open `http://localhost:8082`. Homepage has none either; it's
only a launcher, so open the apps directly (URLs in `hosts/stacks/ops/homepage/services.yaml`). Docs: the built site
is in `/srv/docs/current` on the Dell. MLflow: the job API (basic auth, runbooks/mlflow.md).

## Not on Pocket ID yet, and why

- **Home Assistant:** its phone app can't sign in through a forward-auth proxy. HA keeps its own login (and needs its
  trusted proxies set, P0.16).
- **Open WebUI:** has family accounts to migrate.
- **ntfy, voice-agent:** their own logins or phone apps; a sign-in redirect would break the phone apps and
  API clients (ntfy topics, LiveKit). Use the `signed_in` pattern above only for browser-only apps.
- **Fleet API:** token auth for machines, not people; it stays as is (Homepage only links to it).
