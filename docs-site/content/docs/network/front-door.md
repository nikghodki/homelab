---
title: Front door (Caddy routes)
description: Every *.nghodki.ai route, its backend and how it signs people in; the in-cluster Caddy that serves clients since the P3.3 cutover and reaches every backend directly, and how to add a route.
---

Since the P3.3 cutover (PR #79, 2026-11-15) the front door is **Caddy in k3s** (`edge/edge-caddy`, 2 replicas, one per
Spark), on both Sparks' Tailscale IPs and the edge VIP 192.168.86.11, ports 80 and 443. Its routes are in Git:
`cluster/platform/edge/caddy/Caddyfile` ([below](#in-cluster-front-door-p33)). Decision 0007, runbook
`runbooks/edge.md`.

The old door on dgx-1 (`edge-caddy` and `edge-dnsmasq` in `~/edge-gateway`, and `nginx-gateway` in
`~/voice-assistant/nginx`, all outside the repo) was **stopped on 2026-11-15**: the model plane (model, dgxmanager, ha
and the default route), which it relayed, now goes straight from the in-cluster Caddy to the backends. The containers
and files are kept until 2026-11-22 for a rollback (`runbooks/edge.md`, "Rollback").

## Routes

All in `cluster/platform/edge/caddy/Caddyfile`, on :80 and :443 (wildcard from the Secret `edge/web-tls`). **There is no
:80 → :443 redirect** in general, so devices without the CA still work over http; a few routes redirect themselves.
`10.100.136.1` is dgx-1's direct-cable address, reachable only from the two Sparks, where the Caddy pods run.

| Hostname | Backend | Sign-in | http → https | Notes |
|---|---|---|---|---|
| `id.nghodki.ai` | Pocket ID, 192.168.86.36:1411 (dgx-2) | passkeys | yes (308) | passkeys need HTTPS |
| `ops.nghodki.ai` | ops stack Caddy gate → Homepage, 192.168.86.49:4180 (Dell) | `signed_in` (edge-auth, admins) | yes | |
| `ca.nghodki.ai` | static files in `/etc/caddy/ca` | none | no | `.mobileconfig` and `.crt` get the right content types; in k3s a ConfigMap copy of `hosts/files/web-ca` (checked by CI) |
| `docs.nghodki.ai` | docs Caddy → this site, 192.168.86.49:4181 (Dell) | `signed_in` (edge-auth, admins) | yes | `runbooks/docs-site.md` |
| `auth.nghodki.ai` | `edge/edge-auth` (oauth2-proxy in k3s, by the fixed ClusterIP of `edge-auth-ip`, 10.43.0.54:4180): `/oauth2/*`, `/ping`; anything else → Homepage | it *is* the sign-in (callback for every `signed_in` route) | yes | decision 0011 |
| `model.nghodki.ai` | the `(model_plane)` snippet: `/v1/*`, `/health*` → LiteLLM 10.100.136.1:4000; `/dgxmm*` → 308 to `dgxmanager.nghodki.ai` (DGXMM is only there, behind sign-in, since 2026-11-16); `/v1` → 301 with a slash; else a JSON 404 | LiteLLM keys | no | LiteLLM: 30 min read/write timeouts, no buffering (cold starts). (nginx-gateway until 2026-11-15; `/tts/` dropped, D26) |
| `grafana.nghodki.ai` | 192.168.86.36:3000 | Pocket ID (Grafana's own OAuth) | no | |
| `status.nghodki.ai` | status-gate → Gatus, 192.168.86.49:8081 (Dell) | `signed_in` (edge-auth, admins) | yes | `/health` passes without a session (and `/metrics`, the heartbeat POST on the gate itself) |
| `ntfy.nghodki.ai` | 192.168.86.49:8085 (Dell) | ntfy users | no | `flush_interval -1` so streams aren't buffered. The phone does **not** use this name |
| `phoenix.nghodki.ai` | 192.168.86.36:6006 | Pocket ID (Phoenix OAuth) | no | |
| `mlflow.nghodki.ai` | ml stack Caddy gate, 192.168.86.36:4181 → MLflow | `signed_in` (edge-auth, admins) | yes | |
| `temporal.nghodki.ai` | Temporal UI, 192.168.86.36:8233 | Pocket ID (Temporal UI OIDC) | yes | |
| `argocd.nghodki.ai` | `argocd/argocd-server-host`, fixed ClusterIP 10.43.0.100:80 | Pocket ID (Argo CD OIDC) | yes | Argo CD runs in insecure mode; TLS ends here |
| `litellm-admin.nghodki.ai` | 100.65.137.82:4000 (LiteLLM on dgx-1, by its Tailscale IP) | `session_check` (edge-auth, admins), then the LiteLLM UI login | yes | Host header rewritten to the upstream |
| `controlcenter.nghodki.ai` | 192.168.86.211:8200 (Jetson, RoboClaw control center) | none in Caddy (unverified in the app) | no | old :9119 route was dead |
| `dgxmanager.nghodki.ai` | the `(dgxmm_ui)` snippet: `/dgxmm/*` → DGXMM 10.100.136.1:8090, `/dgxmm/ondemand/*` 404; `/` → 302 `/dgxmm/`; else a JSON 404 pointing at model.nghodki.ai | `session_check` (edge-auth, admins); DGXMM has no login of its own | yes | `/dgxmm/healthz` (the SPA shell) is open for Gatus and Homepage. SSE unbuffered, 1 h reads, 1 MB request limit |
| `webui.nghodki.ai` | 100.65.137.82:3100 (Open WebUI) | Open WebUI accounts | no | 30 min timeouts for streaming |
| `ha.nghodki.ai` | 192.168.86.211:8123 (Home Assistant on the Jetson), websockets, unbuffered | Home Assistant login | no | HA trusts proxies 192.168.86.44 and 192.168.86.36 (the Caddy pods leave from their Spark's LAN IP) and, until the user removes it, 100.65.137.82 |
| anything else, or the IP | `(model_plane)` (as nginx's default server did) | — | — | e.g. `http://192.168.86.11/v1/models` reaches LiteLLM |

`voice-agent.nghodki.ai` (LiveKit route and voice page, broken since LiveKit moved to the Jetson's loopback) was
removed on 2026-11-15 from both doors and DNS (D26, PRs #75, #76; see [Voice](../services/voice.md)).

`nats.nghodki.ai` and `fleet.nghodki.ai` resolve to dgx-1 but are not HTTP routes: NATS (4222, 8883) and the Fleet
broker (8884) and API (8971) have their own TLS with the internal homelab CA.

## How a signed-in route is wired

Two patterns, both in [Pocket ID and sign-in](../security/identity.md):

- **The app speaks OIDC** (Grafana, Phoenix, Temporal UI, Argo CD): Caddy only proxies.
- **The app has no login** (Homepage, the docs, Gatus' UI, MLflow): one line, `import signed_in <backend> <group>`.
  Caddy checks the session with `edge/edge-auth` (one oauth2-proxy in k3s, reachable only from the Caddy pods and
  trusting `X-Forwarded-*` only from pod IPs), sends signed-out browsers to Pocket ID (callback `auth.nghodki.ai`,
  one cookie for `.nghodki.ai`, so one sign-in covers all of them), and proxies to a token gate on the app's host
  (`X-Edge-Origin`; without it 403). Since 2026-11-15; before, each app had its own oauth2-proxy that trusted only
  dgx-1 (decision 0011).

## Add a route

Since the cutover, in Git (`runbooks/edge.md`, "Add or change a route"):

1. Make sure the backend listens on a LAN address (or a fixed ClusterIP / Service, or, for something on dgx-1 that
   only the Caddy pods should reach, dgx-1's direct-cable address 10.100.136.1) and nothing more. There is no relay
   onto dgx-1's Docker networks any more.
2. Add a block inside `(nghodki_routes)` in `cluster/platform/edge/caddy/Caddyfile` (so it's on :80 and :443):

    ```caddy
    @myapp host myapp.nghodki.ai
    handle @myapp {
        @plain protocol http
        redir @plain https://{host}{uri} 308      # only if cookies are Secure or passkeys are used
        reverse_proxy 192.168.86.36:<port>
    }
    ```

3. Add the name to `cluster/platform/edge/names.txt` ([DNS](dns.md#change-a-record)), the Gatus check
   (`hosts/stacks/alerting/gatus/config.yaml.j2`, against the VIP 192.168.86.11) and the Homepage entry
   (`hosts/stacks/ops/homepage/services.yaml`). PR, gated merge; Argo CD rolls the pods (hashed ConfigMaps) within
   ~3 minutes.
4. Check: `curl -sk -o /dev/null -w '%{http_code}\n' https://192.168.86.11/ -H 'Host: myapp.nghodki.ai'`.
5. `.github/scripts/compare-front-doors.sh` on dgx-1 must say `RESULT: same`.

Roll back a route: revert the PR.

## Access log

Since 2026-11-16 Caddy logs every request on :80 and :443 as JSON to stdout; the host collectors on the Sparks ship
it to Loki as `{service_name="edge-caddy"}` ([Observability](../observability/index.md#what-is-collected)). A line has
the method, host, URI, status, duration, size, `User-Agent` and `api_key_hash` (the first 8 hex digits of the
SHA-256 of the caller's API key, the start of LiteLLM's token hash). `Authorization`, `Cookie` and `Set-Cookie` are
`REDACTED`, other key headers and key-like query parameters are hashed, and the `X-Edge-Origin` token is never logged.
`remote_ip` is a pod-network address (kube-proxy masquerades both paths): for k3s nodes (Sparks, Jetson, Dell) it's
the caller's own node (`10.42.1.x` dgx-1, `10.42.0.x` dgx-2, `10.42.2.x` Jetson, `10.42.3.x` Dell); for any other
client, the Spark that took the connection. LogQL and details: `runbooks/edge.md`, "Access log".

## Gotchas

- The default route sends unknown names to the model plane (as nginx-gateway did): a typo in a hostname gets
  LiteLLM's or the JSON 404, not an error page.
- A backend that checks `X-Forwarded-For` (Home Assistant, DGXMM, oauth2-proxy) must trust **both** Caddy pods'
  source addresses: 192.168.86.44 and 192.168.86.36 for LAN backends; 172.23.0.1 and 10.100.136.2 for DGXMM on
  10.100.136.1 (`runbooks/edge.md`, "How it works").

## In-cluster front door (P3.3)

Built and tested in parallel (PR #72), then **cut over** on 2026-11-15: the Tailscale policy for both Sparks (#78;
whether it was pasted into the console is unverified), dgx-2 as a second split-DNS nameserver (console; live), and #79 (dgx-1's Tailscale IP on the tailnet
Services, k3s DNS → edge-dns, Gatus via the VIP, front-door alerts critical, `verify-cutover.sh`). Left in the runbook's
plan: the user's check from a family device, and a failover drill on the tailnet path a day later.

**Failover drill, 2026-11-16** (`runbooks/edge.md`, "Failover drill"): each Spark's front-door path taken away in
turn (k3s stopped and killed, VIPs and Tailscale IP blackholed; nothing rebooted), probed from the Pi over the LAN and
the tailnet. After three fixes (#116, #117, #119) the VIPs move in 12–16 s and every route answers again within
~20 s of losing dgx-1 and ~40 s of losing dgx-2 (it also held the controller-manager lease); before them, sign-in
routes failed for the whole dgx-2 outage and returning dgx-1 restarted k3s on dgx-2 and the Jetson. The stopped old
door can be deleted on 2026-11-22.

| | |
|---|---|
| Caddy | `edge/edge-caddy` (Caddy 2.11.9, 2 replicas, one per Spark), Git-managed `cluster/platform/edge/caddy/Caddyfile`, wildcard cert from the KSOPS Secret `edge/web-tls`; non-root, no capabilities |
| DNS | `edge/edge-dns` (CoreDNS, 2 replicas), zones from `cluster/platform/edge/names.txt` ([DNS](dns.md)) |
| Floating IPs | kube-vip DaemonSet on the Sparks (`kube-system`, ARP on `wlP9s9`): 192.168.86.10 (k3s API), 192.168.86.11 (edge: `edge-dns-lan` :53, `edge-caddy-lan` :80/:443) |
| Tailnet | Services `edge-dns-tailnet`, `edge-caddy-tailnet` with both Sparks' Tailscale IPs (100.65.137.82, 100.124.175.23) as `externalIPs`; kube-proxy DNATs them ahead of Docker |
| Model plane | model, dgxmanager, ha and the default go straight to LiteLLM, DGXMM (10.100.136.1) and HA; the relay through edge-caddy and nginx-gateway was retired on 2026-11-15 (PR #88) |
| Argo CD apps | `kube-vip`, `edge`, `kube-state-metrics` (project `platform`, from `main`) |
| Monitoring | Gatus group `web` via the VIP; group `edge` (DNS on the VIP and both Tailscale IPs over TCP, Caddy on the VIP with cert expiry, DGXMM's UI through the VIP, the API VIP); vmalert `front-door` rules ([Alert rules](../observability/alert-rules.md#front-door-front-dooryml)) |
| Verify | `.github/scripts/verify-cutover.sh` (must end `CUTOVER VERIFIED`; also checks the old door stays stopped); `.github/scripts/compare-front-doors.sh` (every route, the model plane's paths and every name, on two addresses of the door) |
| Rollback | revert in Git; for the old door, restart the stopped containers (backup `~/backups/edge-gateway-2026-11-15.tgz` on dgx-1, root-only, until 2026-11-22). No instant rollback any more (`runbooks/edge.md`, "Rollback") |

Measured before the cutover: deleting the VIP holder's kube-vip pod lost no probes; a frozen holder gave a 14.2 s gap.
A dead Spark: its pods stay in the Services until the node is NotReady (~40 s); tailnet clients that resolved to it
wait for the 30 s TTL.
