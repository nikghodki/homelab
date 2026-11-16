---
title: Front door (Caddy routes)
description: Every *.nghodki.ai route, its backend and how it signs people in; the in-cluster Caddy that serves clients since the P3.3 cutover, edge-caddy on dgx-1 as relay and rollback, and how to add a route.
---

Since the P3.3 cutover (PR #79, 2026-11-15) the front door is **Caddy in k3s** (`edge/edge-caddy`, 2 replicas, one per
Spark), on both Sparks' Tailscale IPs and the edge VIP 192.168.86.11, ports 80 and 443. Its routes are in Git:
`cluster/platform/edge/caddy/Caddyfile` ([below](#in-cluster-front-door-p33)). Decision 0007, runbook
`runbooks/edge.md`.

`edge-caddy` on dgx-1 (Docker, `~/edge-gateway`, **outside the repo**) stays, with the same routes, as the relay to
nginx-gateway (model, dgxmanager, ha and the default route only exist on dgx-1's Docker network) and as the rollback.
It is reached on dgx-1's LAN IP 192.168.86.44; dgx-1's Tailscale IP belongs to the cluster since the cutover. It goes
away when those services move into the cluster (P3.7).

## Files on dgx-1 (old door)

| Path (dgx-1) | What |
|---|---|
| `~/edge-gateway/docker-compose.yml` | `edge-caddy` (`caddy:2.11`, ports 80/443, Docker network `gateway`, `host.docker.internal`) and `edge-dnsmasq` |
| `~/edge-gateway/conf/Caddyfile` | All routes, in the `(nghodki_routes)` snippet imported by `:80` and `:443` |
| `~/edge-gateway/conf/certs/web.crt`, `web.key` | The `*.nghodki.ai` wildcard from the homelab web CA (key 0600, from SOPS `secrets/pki.enc.yaml` → `pki_web_key`) |
| `~/edge-gateway/conf/ca/` | The CA install page for `ca.nghodki.ai` (copy of `hosts/files/web-ca/`) |
| `~/edge-gateway/conf/Caddyfile.bak-*` | Earlier versions, kept by hand before each change |
| `~/voice-assistant/nginx/nginx.conf` | `nginx-gateway`, an internal upstream for model, DGXMM, TTS and HA. It still has a `voice-agent.nghodki.ai` server block (the voice page), but no route or DNS name reaches it since D26 |
| `~/edge-gateway/rollback-nginx.txt` | How to bring back the original nginx-gateway on port 80 |

`:443` uses `tls /etc/caddy/certs/web.crt /etc/caddy/certs/web.key`. **There is no :80 → :443 redirect** in general, so
devices without the CA still work over http. A few routes redirect themselves (below).

## Routes

Same on both doors, except where noted: in k3s, Argo CD is reached by Service name, and the nginx-gateway routes go to
edge-caddy on `192.168.86.44:80`.

| Hostname | Backend | Sign-in | http → https | Notes |
|---|---|---|---|---|
| `id.nghodki.ai` | Pocket ID, 192.168.86.36:1411 (dgx-2) | passkeys | yes (308) | passkeys need HTTPS |
| `ops.nghodki.ai` | oauth2-proxy → Homepage, 192.168.86.49:4180 (Dell) | Pocket ID, client `ops` | yes | |
| `ca.nghodki.ai` | static files in `/etc/caddy/ca` | none | no | `.mobileconfig` and `.crt` get the right content types; in k3s a ConfigMap copy of `hosts/files/web-ca` (checked by CI) |
| `docs.nghodki.ai` | oauth2-proxy-docs → this site, 192.168.86.49:4181 (Dell) | Pocket ID, client `docs` (admins) | yes | added with the docs site (`runbooks/docs-site.md`) |
| `model.nghodki.ai` | (k3s → edge-caddy 192.168.86.44:80 →) `nginx-gateway:80` → `litellm-proxy:4000` (`/v1/`, `/health`); `/dgxmm/` → `dgxmm:8090`; `/tts/` → `kokoro-tts:8880` | LiteLLM keys | no | 30 min read/write timeouts, no buffering (cold starts) |
| `grafana.nghodki.ai` | 192.168.86.36:3000 | Pocket ID (Grafana's own OAuth) | no | |
| `status.nghodki.ai` | status-proxy → Gatus, 192.168.86.49:8081 (Dell) | Pocket ID, client `gatus` | no | `/health`, `/metrics` and the heartbeat POST pass without a session |
| `ntfy.nghodki.ai` | 192.168.86.49:8085 (Dell) | ntfy users | no | `flush_interval -1` so streams aren't buffered. The phone does **not** use this name |
| `phoenix.nghodki.ai` | 192.168.86.36:6006 | Pocket ID (Phoenix OAuth) | no | |
| `mlflow.nghodki.ai` | oauth2-proxy, 192.168.86.36:4181 → MLflow | Pocket ID, client `mlflow` | yes | |
| `temporal.nghodki.ai` | Temporal UI, 192.168.86.36:8233 | Pocket ID (Temporal UI OIDC) | yes | |
| `argocd.nghodki.ai` | in k3s: `argocd-server.argocd.svc.cluster.local:80`; edge-caddy: fixed ClusterIP 10.43.0.100:80 | Pocket ID (Argo CD OIDC) | yes | Argo CD runs in insecure mode; TLS ends here |
| `litellm-admin.nghodki.ai` | 100.65.137.82:4000 (LiteLLM on dgx-1, by its Tailscale IP) | LiteLLM UI login | no | Host header rewritten to the upstream |
| `controlcenter.nghodki.ai` | 192.168.86.211:8200 (Jetson, RoboClaw control center) | none in Caddy (unverified in the app) | no | old :9119 route was dead |
| `dgxmanager.nghodki.ai` | `/` → 302 `/dgxmm/`, then (via edge-caddy) `nginx-gateway:80` → `dgxmm:8090` | none in Caddy (DGXMM UI; Pocket ID after the DGXMM session) | no | |
| `coolify.nghodki.ai` | `/app/*` → 100.65.137.82:6001 (soketi), `/terminal/ws` → :6002, rest → :8000 | Coolify login | no | |
| `webui.nghodki.ai` | 100.65.137.82:3100 (Open WebUI) | Open WebUI accounts | no | 30 min timeouts for streaming |
| `ha.nghodki.ai` | no Caddy route: falls through (via edge-caddy) to `nginx-gateway`, whose `ha.nghodki.ai` server proxies to 192.168.86.211:8123 | Home Assistant login | no | HA trusts proxies 192.168.86.44 and 100.65.137.82 (P0.16) |
| anything else, or the IP | `nginx-gateway:80` (default; from k3s via edge-caddy) | — | — | e.g. `http://192.168.86.44/v1` reaches LiteLLM |

`voice-agent.nghodki.ai` (LiveKit route and voice page, broken since LiveKit moved to the Jetson's loopback) was
removed on 2026-11-15 from both doors and DNS (D26, PRs #75, #76; see [Voice](../services/voice.md)).

`nats.nghodki.ai` and `fleet.nghodki.ai` resolve to dgx-1 but are not HTTP routes: NATS (4222, 8883) and the Fleet
broker (8884) and API (8971) have their own TLS with the internal homelab CA.

## How a signed-in route is wired

Two patterns, both in [Pocket ID and sign-in](../security/identity.md):

- **The app speaks OIDC** (Grafana, Phoenix, Temporal UI, Argo CD): Caddy only proxies.
- **The app has no login** (Homepage, Gatus, MLflow): an oauth2-proxy container next to the app is the only thing
  published on the LAN; Caddy points at it. oauth2-proxy trusts `X-Forwarded-*` only from 192.168.86.44 (the docs
  proxy also from 192.168.86.36). Requests from the Caddy pod on dgx-2 probably arrive from 192.168.86.36, so the
  `status` and `mlflow` proxies may ignore their forwarded headers (unverified).

## Add a route

Since the cutover, in Git (`runbooks/edge.md`, "Add or change a route"):

1. Make sure the backend listens on a LAN address (or a fixed ClusterIP / Service) and nothing more.
2. Add a block inside `(nghodki_routes)` in `cluster/platform/edge/caddy/Caddyfile` (so it's on :80 and :443).
   Something only on dgx-1's Docker network goes to `192.168.86.44:80`:

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
5. Old door, needed for a route behind nginx-gateway or to keep the rollback complete: back up
   `~/edge-gateway/conf/Caddyfile` (`cp ... Caddyfile.bak-<what>-$(date +%Y%m%d%H%M%S)`), add the same block,
   `docker exec edge-caddy caddy validate --config /etc/caddy/Caddyfile`, `docker restart edge-caddy` (a `caddy
   reload` hasn't always taken effect). Then `.github/scripts/compare-front-doors.sh` on dgx-1 must say
   `RESULT: same`.

Roll back a route: revert the PR (old door: copy the `.bak` file back and restart edge-caddy).

## Gotchas

- edge-caddy's `caddy:2.11` is a floating tag and the container isn't managed by Ansible, so Renovate never sees it
  (the in-cluster Caddy is pinned, 2.11.9).
- The default route sends unknown names to `nginx-gateway`. A typo in a hostname reaches nginx, not an error page.
- Restarting edge-caddy drops the nginx-gateway routes (model, dgxmanager, ha) for a few seconds.
- `X-Forwarded-For` for nginx-gateway routes is the Caddy pod's node, not the client: edge-caddy overwrites it.

## In-cluster front door (P3.3)

Built and tested in parallel (PR #72), then **cut over** on 2026-11-15: the Tailscale policy for both Sparks (#78;
whether it was pasted into the console is unverified), dgx-2 as a second split-DNS nameserver (console; live), and #79 (dgx-1's Tailscale IP on the tailnet
Services, k3s DNS → edge-dns, Gatus via the VIP, front-door alerts critical, `verify-cutover.sh`). Left in the runbook's
plan: the user's check from a family device, and a failover drill on the tailnet path a day later.

| | |
|---|---|
| Caddy | `edge/edge-caddy` (Caddy 2.11.9, 2 replicas, one per Spark), Git-managed `cluster/platform/edge/caddy/Caddyfile`, wildcard cert from the KSOPS Secret `edge/web-tls`; non-root, no capabilities |
| DNS | `edge/edge-dns` (CoreDNS, 2 replicas), zones from `cluster/platform/edge/names.txt` ([DNS](dns.md)) |
| Floating IPs | kube-vip DaemonSet on the Sparks (`kube-system`, ARP on `wlP9s9`): 192.168.86.10 (k3s API), 192.168.86.11 (edge: `edge-dns-lan` :53, `edge-caddy-lan` :80/:443) |
| Tailnet | Services `edge-dns-tailnet`, `edge-caddy-tailnet` with both Sparks' Tailscale IPs (100.65.137.82, 100.124.175.23) as `externalIPs`; kube-proxy DNATs them ahead of Docker |
| nginx-gateway routes | model, dgxmanager, ha and the default go to edge-caddy on `192.168.86.44:80`, which relays to nginx-gateway (until P3.7) |
| Argo CD apps | `kube-vip`, `edge`, `kube-state-metrics` (project `platform`, from `main`) |
| Monitoring | Gatus group `web` via the VIP; group `edge` (DNS on the VIP and both Tailscale IPs over TCP, Caddy on the VIP with cert expiry, the edge-caddy relay on `.44:80`, the API VIP); vmalert `front-door` rules ([Alert rules](../observability/alert-rules.md#front-door-front-dooryml)) |
| Verify | `.github/scripts/verify-cutover.sh` (must end `CUTOVER VERIFIED`); `.github/scripts/compare-front-doors.sh` (every route and name, old vs new) |
| Rollback | revert #79, or (seconds) drop 100.65.137.82 from the two tailnet Services; the old door never stopped listening (`runbooks/edge.md`, "Rollback") |

Measured before the cutover: deleting the VIP holder's kube-vip pod lost no probes; a frozen holder gave a 14.2 s gap.
A dead Spark: its pods stay in the Services until the node is NotReady (~40 s); tailnet clients that resolved to it
wait for the 30 s TTL.
