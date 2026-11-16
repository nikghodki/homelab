# 0011: One sign-in proxy: oauth2-proxy `edge-auth` in k3s behind the front door's forward auth

- Date: 2026-11-15
- Status: decided (nikghodki, tool review recommendation 5 / §2.2); applied app by app (runbooks/sign-in.md)

## Context

Four browser apps have no login of their own and each had its own oauth2-proxy and Pocket ID client:
Homepage (`ops`, Dell :4180), the docs site (`docs`, Dell :4181), Gatus' status page (`gatus`, Dell :8081) and MLflow
(`mlflow`, dgx-2 :4181). Four cookie secrets, four clients, four sign-ins, and four `trusted_proxy_ips` lists that still
named only dgx-1 although the front door (decision 0007) runs on both Sparks. Gatus stays behind a proxy rather than
using its own OIDC: Gatus' `security.oidc` panics at start when Pocket ID is unreachable, which would stop the checks
during a Spark outage. Apps with native OIDC (Grafana, Phoenix, Temporal UI, Argo CD) are out of scope and keep their
clients.

## Decision

- **One oauth2-proxy 7.15.6, `edge/edge-auth`, with one Pocket ID client `edge-auth`.** Deployment in namespace
  `edge`, 2 replicas, one per Spark (required anti-affinity, `nghodki.ai/role: gpu`, PDB `minAvailable: 1`), image
  pinned by digest, requests/limits (10m/24Mi, 200m/64Mi), non-root, read-only root filesystem, no capabilities, no
  service-account token. Config in Git (`cluster/platform/edge/edge-auth/oauth2-proxy.cfg`, a hashed ConfigMap);
  the client secret and the cookie secret come from the KSOPS Secret `edge-auth` (`edge-auth.enc.yaml`). Sessions are
  encrypted cookies, so the replicas share nothing but that Secret.
- **The in-cluster Caddy calls it for every request to a signed-in route** (forward auth): one snippet,
  `import signed_in <backend> <group>`, is the whole route. It
  1. redirects http to https (the cookie is `Secure`);
  2. asks `edge-auth`'s `/oauth2/auth?allowed_groups=<group>` (per-route group check; all four routes ask for
     `admins`, as before; the Pocket ID client also admits only `admins`);
  3. on 2xx copies any `Set-Cookie` from that answer to the browser (the hourly token refresh happens there;
     Caddy's `forward_auth` shortcut can't do this, so the snippet spells out the `reverse_proxy` it expands to), then
     proxies to the backend with the **edge origin token** (`X-Edge-Origin`) and without the `_edge_auth*` cookies;
  4. on 401 lets `edge-auth`'s `/oauth2/start` answer in place (CSRF cookie, 302 to Pocket ID), with the original URL
     in `X-Forwarded-Uri`, so nothing has to be URL-encoded in Caddy;
  5. passes anything else through (403: signed in but not in the group; 502: `edge-auth` down, so it fails closed).
- **A dedicated callback host, `https://auth.nghodki.ai`**, not `/oauth2/*` on each app's host. With forward auth the
  proxy never sees the app's host for the callback anyway; one fixed `redirect_url` means one callback URL in Pocket
  ID for every app, so **putting a new app behind sign-in is one Caddy block, with no Pocket ID change** (per-host
  callbacks would need the client's callback list edited for each app). The cost is one more name in `names.txt` and
  one extra redirect hop at sign-in. `whitelist_domains = [".nghodki.ai"]` lets it send the browser back to any app.
  `auth.nghodki.ai` serves `edge-auth`'s `/oauth2/*` (callback, `sign_out`) and `/ping`; anything else redirects to
  Homepage.
- **Cookie `_edge_auth` for `.nghodki.ai`**: `Secure`, `HttpOnly`, `SameSite=Lax`, 7 days (`cookie_expire = 168h`,
  as the docs proxy had), tokens refreshed after 1 h. One sign-in covers every signed-in route. CSRF cookies per
  request (several tabs can sign in at once).
- **Trusted proxies: the Caddy pods only.** `trusted_proxy_ips = ["10.42.0.0/16"]` (pod CIDR), and the NetworkPolicy
  `edge-auth` admits only `edge-caddy` pods on :4180, so no other pod or host can reach it, let alone set
  `X-Forwarded-*`. That also fixes the old lists that trusted only dgx-1.
- **Pocket ID is reached the same way as Argo CD does** (kube-dns → `edge-dns` → the VIP → Caddy), trusting only the
  homelab web CA (`provider_ca_files`, the CA page's ConfigMap). The endpoints are configured, not discovered
  (`skip_oidc_discovery`), so `edge-auth` starts, and existing sessions keep working until their next refresh, while
  Pocket ID is down.
- **Backends listen on their host's LAN IP behind a token gate.** The apps themselves have no auth, so each host's
  existing Caddy (or a small new one) is published on the LAN address only and answers only requests carrying
  `X-Edge-Origin: <token>` (a 43-character random token, `edge_origin_token` in `secrets/console.enc.yaml`, copied
  into the `edge-auth` Secret; rendered 0600 into the gates by Ansible). It strips the header before the app. Without
  it: 403. Unauthenticated paths that something else needs stay open on the gate: Gatus' `/health`, `/metrics`
  (VictoriaMetrics) and the heartbeat endpoint (Alertmanager), the docs' `/healthz`, MLflow's job API on :5000 (basic
  auth, unchanged). Same ports as the old proxies (Dell 4180, 4181, 8081; dgx-2 4181), so the scrape and heartbeat
  configs don't change.
- **Gatus' checking is not behind anything**: it runs on the Dell regardless; only its web UI is signed in.

## Alternatives considered

- **Per-host `/oauth2/start` and `/oauth2/callback`**: no extra name, but every app adds a callback URL to the Pocket
  ID client, and the cookie would still need `.nghodki.ai` for one sign-in. Rejected for the one-block goal.
- **Caddy's `forward_auth` shortcut**: drops the auth response's `Set-Cookie` on success, so the refreshed session
  never reaches the browser and every request after the first hour would refresh again (and fail once Pocket ID
  rotates the refresh token). Written out instead.
- **Redirect to `https://auth.nghodki.ai/oauth2/start?rd={scheme}://{host}{uri}`**: Caddy has no URL-encoding
  placeholder, so a query string in the original URL would be cut at its first `&`.
- **Redis/Valkey session store** (would make the cookie a small ticket and refresh server-side): a stateful pod
  whose loss signs everyone out and which the front door would then depend on. Not needed.
- **Firewalling the backend ports to the Sparks' IPs** instead of the token: any process on a Spark (every pod
  leaves with its node's IP) would still reach the apps, and Docker's published ports bypass the host firewall
  (ufw) unless rules go in `DOCKER-USER`. The token check needs no firewall changes and works from either Spark.
- **mTLS from Caddy to the backends**: stronger than a shared token on the LAN, but a client cert per Caddy pod and a
  CA on each gate for four apps. Revisit if anything ever leaves the LAN.
- **caddy-security / Authelia / tinyauth**: a custom Caddy build or a heavier or younger stack (tool review §2.2).
- **Gatus' native OIDC**: the review's suggestion; rejected because Gatus panics at start without Pocket ID (above).
- **Running `edge-auth` in `console` or on the Dell**: the front door already runs on the Sparks, and every signed-in
  app is only reachable through it, so a proxy next to Caddy **adds no new failure mode**; on the Dell it would add a
  hop over Wi-Fi and a host the front door depends on.

## Consequences

- **3 fewer containers** after the migration (four oauth2-proxies on the hosts → two small pods; the docs and MLflow
  gates reuse existing Caddies, Gatus' gate is a Caddy instead of an oauth2-proxy), **4 Pocket ID clients → 1**, 4
  cookie secrets → 1. A new app: one `import signed_in` block (runbooks/sign-in.md).
- If `edge-auth` is down, every signed-in route answers 502 (fail closed), and Gatus' checks keep running. If Pocket
  ID is down, signed-in sessions work until their next hourly refresh; new sign-ins fail.
- The session cookie goes to every `*.nghodki.ai` backend, including routes not behind sign-in (Home Assistant, Open
  WebUI, ...); the signed-in routes strip it. A compromised backend could replay it through the door for up to 7
  days. Acceptable for one admin on a home network; rotating the cookie secret signs everyone out. Stripping it on
  every route is a one-line follow-up in `(nghodki_routes)`.
- The edge origin token travels in clear over the LAN from the Sparks to the Dell/dgx-2, as the session cookies did
  before (Caddy → oauth2-proxy was plain HTTP too). Anyone who can read LAN traffic and take the token can bypass
  sign-in for these four apps; rotate it (runbooks/sign-in.md) if a LAN device is suspect.
- Removing a person from `admins` in Pocket ID takes effect at the next refresh (≤ 1 h).
