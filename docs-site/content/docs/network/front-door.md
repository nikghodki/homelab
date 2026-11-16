---
title: Front door (Caddy routes)
description: Every *.nghodki.ai route on dgx-1's edge-caddy, its backend, how it signs people in, and how to add one.
---

The front door is `edge-caddy` on dgx-1, ports 80 and 443. Every `*.nghodki.ai` web name goes through it. It is
**outside the repo** today, in `~/edge-gateway` on dgx-1 (P3.3 moves it into k3s).

## Files

| Path (dgx-1) | What |
|---|---|
| `~/edge-gateway/docker-compose.yml` | `edge-caddy` (`caddy:2.11`, ports 80/443, Docker network `gateway`, `host.docker.internal`) and `edge-dnsmasq` |
| `~/edge-gateway/conf/Caddyfile` | All routes, in the `(nghodki_routes)` snippet imported by `:80` and `:443` |
| `~/edge-gateway/conf/certs/web.crt`, `web.key` | The `*.nghodki.ai` wildcard from the homelab web CA (key 0600, from SOPS `secrets/pki.enc.yaml` → `pki_web_key`) |
| `~/edge-gateway/conf/ca/` | The CA install page for `ca.nghodki.ai` (copy of `hosts/files/web-ca/`) |
| `~/edge-gateway/conf/Caddyfile.bak-*` | Earlier versions, kept by hand before each change |
| `~/voice-assistant/nginx/nginx.conf` | `nginx-gateway`, an internal upstream for model, DGXMM, TTS, the voice page and HA |
| `~/edge-gateway/rollback-nginx.txt` | How to bring back the original nginx-gateway on port 80 |

`:443` uses `tls /etc/caddy/certs/web.crt /etc/caddy/certs/web.key`. **There is no :80 → :443 redirect** in general, so
devices without the CA still work over http. A few routes redirect themselves (below).

## Routes

| Hostname | Backend | Sign-in | http → https | Notes |
|---|---|---|---|---|
| `id.nghodki.ai` | Pocket ID, 192.168.86.36:1411 (dgx-2) | passkeys | yes (308) | passkeys need HTTPS |
| `ops.nghodki.ai` | oauth2-proxy → Homepage, 192.168.86.49:4180 (Dell) | Pocket ID, client `ops` | yes | |
| `ca.nghodki.ai` | static files in `/etc/caddy/ca` | none | no | `.mobileconfig` and `.crt` get the right content types |
| `model.nghodki.ai` | `nginx-gateway:80` → `litellm-proxy:4000` (`/v1/`, `/health`); `/dgxmm/` → `dgxmm:8090`; `/tts/` → `kokoro-tts:8880` | LiteLLM keys | no | 30 min read/write timeouts, no buffering (cold starts) |
| `grafana.nghodki.ai` | 192.168.86.36:3000 | Pocket ID (Grafana's own OAuth) | no | |
| `status.nghodki.ai` | status-proxy → Gatus, 192.168.86.49:8081 (Dell) | Pocket ID, client `gatus` | no | `/health`, `/metrics` and the heartbeat POST pass without a session |
| `ntfy.nghodki.ai` | 192.168.86.49:8085 (Dell) | ntfy users | no | `flush_interval -1` so streams aren't buffered. The phone does **not** use this name |
| `phoenix.nghodki.ai` | 192.168.86.36:6006 | Pocket ID (Phoenix OAuth) | no | |
| `mlflow.nghodki.ai` | oauth2-proxy, 192.168.86.36:4181 → MLflow | Pocket ID, client `mlflow` | yes | |
| `temporal.nghodki.ai` | Temporal UI, 192.168.86.36:8233 | Pocket ID (Temporal UI OIDC) | yes | |
| `argocd.nghodki.ai` | fixed ClusterIP 10.43.0.100:80 (reached through dgx-1's kube-proxy) | Pocket ID (Argo CD OIDC) | yes | Argo CD runs in insecure mode; TLS ends here |
| `litellm-admin.nghodki.ai` | 100.65.137.82:4000 (LiteLLM on dgx-1, by its Tailscale IP) | LiteLLM UI login | no | Host header rewritten to the upstream |
| `controlcenter.nghodki.ai` | 192.168.86.211:8200 (Jetson, RoboClaw control center) | none in Caddy (unverified in the app) | no | old :9119 route was dead |
| `dgxmanager.nghodki.ai` | `/` → 302 `/dgxmm/`, then `nginx-gateway:80` → `dgxmm:8090` | none in Caddy (DGXMM UI; Pocket ID after the DGXMM session) | no | |
| `coolify.nghodki.ai` | `/app/*` → 100.65.137.82:6001 (soketi), `/terminal/ws` → :6002, rest → :8000 | Coolify login | no | |
| `webui.nghodki.ai` | 100.65.137.82:3100 (Open WebUI) | Open WebUI accounts | no | 30 min timeouts for streaming |
| `ha.nghodki.ai` | no Caddy route: falls through to `nginx-gateway`, whose `ha.nghodki.ai` server proxies to 192.168.86.211:8123 | Home Assistant login | no | HA trusts proxies 192.168.86.44 and 100.65.137.82 (P0.16) |
| `voice-agent.nghodki.ai` | its own site block: `/rtc*`, `/twirp/*` → 100.65.137.82:7880; rest → `nginx-gateway` (voice page; `/token` → `host.docker.internal:7890`) | — | — | **Broken at check time**: nothing listens on dgx-1:7880 (LiveKit runs on the Jetson, 127.0.0.1:7880); `/rtc` returned 502 |
| anything else, or the IP | `nginx-gateway:80` (default) | — | — | e.g. `http://192.168.86.44/v1` reaches LiteLLM |

`nats.nghodki.ai` and `fleet.nghodki.ai` resolve to dgx-1 but are not HTTP routes: NATS (4222, 8883) and the Fleet
broker (8884) and API (8971) have their own TLS with the internal homelab CA.

## How a signed-in route is wired

Two patterns, both in [Pocket ID and sign-in](../security/identity.md):

- **The app speaks OIDC** (Grafana, Phoenix, Temporal UI, Argo CD): Caddy only proxies.
- **The app has no login** (Homepage, Gatus, MLflow): an oauth2-proxy container next to the app is the only thing
  published on the LAN; Caddy points at it. oauth2-proxy trusts `X-Forwarded-*` only from 192.168.86.44.

## Add a route

1. Make sure the backend listens on a LAN address (or a fixed ClusterIP) and nothing more.
2. On dgx-1, back up the file: `cp ~/edge-gateway/conf/Caddyfile ~/edge-gateway/conf/Caddyfile.bak-<what>-$(date +%Y%m%d%H%M%S)`.
3. Add a block inside `(nghodki_routes)`:

    ```caddy
    @myapp host myapp.nghodki.ai
    handle @myapp {
        @plain protocol http
        redir @plain https://{host}{uri} 308      # only if cookies are Secure or passkeys are used
        reverse_proxy 192.168.86.36:<port>
    }
    ```

4. Validate: `docker exec edge-caddy caddy validate --config /etc/caddy/Caddyfile`.
5. `docker restart edge-caddy` (a `caddy reload` hasn't always taken effect).
6. Add the DNS records ([DNS](dns.md)), the Gatus check (`hosts/stacks/alerting/gatus/config.yaml.j2`), and the Homepage
   entry (`hosts/stacks/ops/homepage/services.yaml`) in a PR.
7. Check: `curl -sk -o /dev/null -w '%{http_code}\n' https://192.168.86.44/ -H 'Host: myapp.nghodki.ai'`.

Roll back: copy the `.bak` file back and restart edge-caddy.

## Gotchas

- `caddy:2.11` is a floating tag and the container isn't managed by Ansible, so Renovate never sees it.
- The default route sends unknown names to `nginx-gateway`. A typo in a hostname reaches nginx, not an error page.
- Caddy's TLS for `voice-agent.nghodki.ai` is a separate site block with the same cert.
- Restarting edge-caddy drops every web session for a few seconds, including Pocket ID logins in progress.
