# The front door: `*.nghodki.ai` DNS and HTTPS (plan P3.3)

Design and test results: [decision 0007](../decisions/0007-edge-in-cluster.md). Certificates: [web-https.md](web-https.md).

**Status: cut over (P3.3); the old door is retired (2026-11-15).** The tailnet (every client) uses the in-cluster door
on both Sparks' Tailscale IPs; the LAN view is on the VIP. Caddy reaches every backend directly: the relay through
dgx-1's edge-caddy and nginx-gateway is gone, and edge-caddy, edge-dnsmasq and nginx-gateway are **stopped**
(containers kept, `restart: no`; backup `~/backups/edge-gateway-2026-11-15.tgz` on dgx-1, root-only, see [Rollback](#rollback)).

| | In-cluster door (live) |
|---|---|
| DNS | `edge/edge-dns` (CoreDNS, 2 replicas): VIP `192.168.86.11:53` (LAN view), both Sparks' Tailscale IPs `:53` (tailnet view) |
| HTTPS | `edge/edge-caddy` (Caddy, 2 replicas): VIP `192.168.86.11:80/443`, both Sparks' Tailscale IPs `:80/443` |
| Sign-in | `edge/edge-auth` (oauth2-proxy, 2 replicas) for the routes that use `import signed_in`: ops, docs, status, mlflow; callback host `auth.nghodki.ai` ([sign-in.md](sign-in.md), decision 0011) |
| Floating IPs | kube-vip (`kube-system`, DaemonSet on the Sparks): `192.168.86.10` (k3s API), `192.168.86.11` (edge) |
| Config | `cluster/platform/edge/`: `names.txt` (every name), `caddy/Caddyfile`, generated `coredns/*.db`, `web-tls.enc.yaml`, `edge-auth.yaml` + `edge-auth/oauth2-proxy.cfg` + `edge-auth.enc.yaml` |
| Argo CD apps | `kube-vip`, `edge`, `kube-state-metrics` (project `platform`) |
| Retired (stopped on dgx-1) | edge-caddy (`~/edge-gateway/conf/Caddyfile`), edge-dnsmasq (`~/edge-gateway/dnsmasq/dnsmasq.conf`), nginx-gateway (`~/voice-assistant/nginx/nginx.conf`) |

## How it works

- **LAN**: `*.nghodki.ai` → `192.168.86.11`, which kube-vip keeps on one Spark's `wlP9s9` (gratuitous ARP; measured
  failover 0 s graceful, 14 s when the holder dies). kube-proxy on that Spark DNATs it to the CoreDNS/Caddy pods.
  Nothing uses LAN DNS today (the router doesn't forward `nghodki.ai`), so this view is for fleet hosts and later.
- **Tailnet** (every client today): Tailscale split DNS for `nghodki.ai` → the Sparks' Tailscale IPs. Each CoreDNS
  replica answers with **its own Spark's** Tailscale IP (zone `tailnet-<node>.db`, TTL 30 s), so an answer never names
  a dead Spark; Caddy on either Tailscale IP reaches either Caddy pod. Non-`nghodki.ai` queries are REFUSED there.
- **Not through Caddy**: `nats`, `fleet` (dgx-1), `backup` (dgx-2), the host names (`jetson`, `pi`, ...) and
  `k8s` (the API VIP on the LAN; on the tailnet, the answering Spark's Tailscale IP).
- **The model plane** (what nginx-gateway served until 2026-11-15) is the `(model_plane)` snippet, used by
  `model.nghodki.ai` and the door by IP or an unknown name (nginx's default server): `/v1/*` and `/health*` → LiteLLM
  `10.100.136.1:4000` (no buffering, 30 min timeouts), `/v1` → 301 to the slashed path, `/dgxmm*` → 308 to
  `dgxmanager.nghodki.ai`, anything else → a JSON 404.
  `10.100.136.1` is dgx-1's direct-cable address: only the two Sparks (where Caddy runs) reach it.
  `dgxmanager.nghodki.ai` serves the DGXMM UI only (2026-11-15), behind sign-in (2026-11-16, `session_check admins`:
  DGXMM has no login of its own): the `(dgxmm_ui)` snippet, `/dgxmm/*` → DGXMM `10.100.136.1:8090` (SSE, 1 h read
  timeout, 1 MB request limit), `/dgxmm/ondemand/*` → 404 (LiteLLM-only, on the Docker network), `/` → `/dgxmm/` 302,
  `/v1/` → a JSON 404 pointing at `model.nghodki.ai`. `/dgxmm/healthz` (the SPA shell) is open for the checks.
  `litellm-admin.nghodki.ai` is behind the same sign-in, then LiteLLM's own UI login.
- **DGXMM** publishes `:8090` only on `10.100.136.1` and trusts `X-Forwarded-For` from `10.100.136.2` (the Caddy pod
  on dgx-2) and `172.23.0.1` (the pod on dgx-1, masqueraded onto the Docker network `gateway`):
  `DGXMM_BIND` / `DGXMM_TRUSTED_PROXIES` in `~/workspace/dgx-model-manager/.env` (the user's repo, not in Git here).
  A new Caddy node, or a change of Docker network, needs its source address there (check with
  `docker logs dgxmm | grep 'GET /dgxmm/'` while probing from the pod).
- **Home Assistant** (`ha.nghodki.ai` → `192.168.86.211:8123`, websockets) trusts `X-Forwarded-For` from both
  Sparks' LAN IPs `192.168.86.44` and `192.168.86.36` (the pods leave from their node's IP); set in HA's UI by the
  user. Without the entry HA answers 400 to every request through that Spark's pod.

- **No cluster DNS on the door's path.** Every Caddy upstream is an IP: LAN/cable/Tailscale addresses, and for
  in-cluster backends a fixed ClusterIP (edge-auth `10.43.0.54`, Argo CD `10.43.0.100`). With Service names, a dead
  kube-dns (one replica until 2026-11-16, on dgx-2) broke sign-in for every new connection (the failover drill).
  kube-dns has two replicas now, one per Spark (`cluster/platform/cluster-dns/coredns-replicas.ssa-patch.yaml`).

- **Signed-in routes** (apps without their own login: Homepage, docs, Gatus' UI, MLflow) are one line each,
  `import signed_in <backend> <group>`: Caddy asks `edge-auth` (`/oauth2/auth?allowed_groups=<group>`) on every
  request, sends signed-out browsers to Pocket ID (callback `https://auth.nghodki.ai`, one cookie for `.nghodki.ai`),
  and proxies to the backend with the `X-Edge-Origin` token (env `EDGE_ORIGIN_TOKEN` from the Secret `edge-auth`)
  and without the session cookie. The backends are token gates on their host's LAN IP that refuse anything else
  (403). How to add one: [sign-in.md](sign-in.md#apps-without-their-own-login-one-block-in-the-caddyfile).
  `edge-auth` is reachable only from the Caddy pods (NetworkPolicy) and trusts `X-Forwarded-*` only from pod IPs.

## Add or change a route

Only the in-cluster door (the old one on dgx-1 is retired):

1. A new name: add `<name>  edge` (or a host target, see the file's header) to `cluster/platform/edge/names.txt`, then
   `.github/scripts/edge-zone.py generate` (writes the zones; CI runs `check`).
2. The route: add a `@<name> host <name>.nghodki.ai` / `handle` block to `cluster/platform/edge/caddy/Caddyfile`
   (inside `(nghodki_routes)`, so it's on :80 and :443). Backends are LAN IPs and ports, a Service name, or, for a
   service on dgx-1, a port it publishes on the LAN, its Tailscale IP or `10.100.136.1` (the direct cable; there's no
   relay onto dgx-1's Docker networks any more).
3. PR, gated merge; Argo CD rolls the pods (the ConfigMaps are hashed) within ~3 minutes.
4. `.github/scripts/compare-front-doors.sh` on dgx-1 must say `RESULT: same`.



## Checks

```bash
cd ~/homelab && .github/scripts/compare-front-doors.sh                      # LAN VIP vs dgx-2's Tailscale IP, every route + DNS
.github/scripts/compare-front-doors.sh -n 100.65.137.82 -o 192.168.86.11 -v tailnet    # tailnet path (dgx-1's Tailscale IP)
.github/scripts/verify-cutover.sh                                           # also: the old door stays stopped
.github/scripts/verify-edge-auth.sh                                         # sign-in: every signed-in route -> Pocket ID (client edge-auth), gates 403
.github/scripts/verify-edge-auth.sh -n 100.124.175.23 -B                    # the same over the tailnet
export KUBECONFIG=~/.kube/config
kubectl -n edge get pods -o wide; kubectl -n edge get svc                    # 2+2 pods, one per Spark; VIP in EXTERNAL-IP
kubectl -n kube-system get lease plndr-cp-lock plndr-svcs-lock              # which Spark holds .10 / .11
ip -br addr show wlP9s9                                                     # the VIPs appear on the holder only
```

From a host without the repo (the MacBook Air), stream the files from dgx-1 and run it there (nothing is written on
the laptop): `ssh dgx-1 'tar -C ~/homelab -czf - cluster/platform/edge/names.txt cluster/platform/edge/coredns
hosts/files/pki/web-ca.crt .github/scripts/compare-front-doors.sh' | ssh air 'mkdir -p /tmp/f && tar -C /tmp/f -xzf - &&
bash /tmp/f/.github/scripts/compare-front-doors.sh -r /tmp/f'`.

**Test ARP from a non-node.** The Dell and the Jetson are k3s nodes: their own kube-proxy DNATs the VIP, so they never
ARP for it. The MacBook Air (or the Pi) is a real LAN client (`arp -n 192.168.86.11` shows which Spark's MAC it uses).

Sign-in monitoring: Gatus `auth.nghodki.ai (edge-auth)` (`/ping` through the VIP), the four signed-in routes'
302s, and `... refuses direct access` (403) for each gate; vmalert `EdgeReplicasDown` covers `edge-auth` too (every
Deployment in `edge`).

Monitoring: Gatus group `edge` on the Dell (DNS on the VIP and on dgx-2's Tailscale IP over TCP, Caddy on the VIP with
the cert's expiry, grafana through the VIP, the API VIP); vmalert `front-door` (`KubeVipNotReady`, `KubeVipDown`,
`EdgeReplicasDown`, `EdgeFrontDoorDown`, `KubeStateMetricsDown`) from kube-state-metrics at `10.43.0.120`.

## Access log

Caddy writes one JSON line per request on :80 and :443 (every host, `model.nghodki.ai` included; not the :8081 probes)
to stdout (the `(access_log)` snippet). The host collector on each Spark tails the pod's CRI log
(`/var/log/pods/edge_edge-caddy-*/caddy/*.log`, role `otel_host_collector`, `otel_host_collector_pod_logs` in
`hosts/group_vars/sparks.yml`) and sends it to Loki on dgx-2 as `{service_name="edge-caddy"}`, with `host_name`,
`k8s_pod_name` and `fleet_host` (30 days, like every Loki stream). Caddy's own startup/error lines are in the same stream
(no `request` field).

- **Logged**: `request.remote_ip` / `client_ip`, `host`, `method`, `uri`, `proto`, request headers (`User-Agent`, ...),
  `tls.server_name`, `status`, `duration` (s), `size` (response bytes), `bytes_read`, response headers, and
  **`api_key_hash`**: the first 8 hex digits of the SHA-256 of the caller's key (`Authorization: Bearer <key>`, or
  `x-api-key`), absent without one. It's the start of LiteLLM's hashed token, so it names the key without logging it:
  `printf %s "$KEY" | sha256sum | cut -c1-8`, or match the start of the token hash in LiteLLM's UI (Virtual Keys).
- **Redacted**: `Authorization`, `Proxy-Authorization`, `Cookie` and `Set-Cookie` are `REDACTED` (Caddy's default;
  `log_credentials` stays off). `X-Api-Key`, `Api-Key`, `X-Goog-Api-Key` and the query parameters `key`, `api_key`,
  `access_token`, `token` are replaced by the same 8-digit hash. `X-Edge-Origin` is only added on the way to the
  backend (`header_up`): the log has the client's request, so it never appears (tested with the pinned image).
- **`remote_ip` is a pod-network address, not the client's IP.** Both Services masquerade
  (`externalTrafficPolicy: Cluster` on the VIP; `externalIPs` on the tailnet Service, where `Local` isn't allowed):
  the node whose kube-proxy took the connection appears as `10.42.<n>.0` (to the other Spark's pod) or `10.42.<n>.1`
  (to its own pod). Fleet hosts that are k3s nodes catch the door's IPs in their **own** kube-proxy, so for them it
  names the caller: `10.42.1.x` dgx-1, `10.42.0.x` dgx-2, `10.42.2.x` Jetson, `10.42.3.x` Dell
  (`kubectl get nodes -o custom-columns=N:.metadata.name,C:.spec.podCIDR`). Any other client (Mac, phone, over the
  tailnet or the LAN) shows the Spark that received it; tell those apart by `api_key_hash` and `User-Agent`. The
  real IP would need `Local` on LoadBalancer Services for both paths (then a Spark's IP reaches only its own pod):
  not done.

Who called `/v1/` in the last hour, by key and by source address (Grafana → Explore → Loki):

```logql
sum by (api_key_hash, remote_ip) (
  count_over_time({service_name="edge-caddy"} | json remote_ip="request.remote_ip", uri="request.uri", api_key_hash
    | uri =~ "/v1/.*" [1h])
)
```

Raw lines: `{service_name="edge-caddy"} | json | request_host="model.nghodki.ai"`. From dgx-1 without Grafana:
`ssh -n nikghodki-dgx-2@192.168.86.36 'docker run --rm --network observe_default curlimages/curl:8.17.0 -sG
http://loki:3100/loki/api/v1/query_range --data-urlencode query={service_name=\"edge-caddy\"} --data-urlencode since=1h'`.
Straight from a pod: `kubectl -n edge logs deploy/edge-caddy | grep http.log.access` (one pod).

## Failover

- **kube-vip holder fails**: the other Spark takes the lease after ≤10 s and announces the VIP (measured 14.2 s gap
  from a LAN client). A graceful stop (pod deleted, rollout) hands over with no gap.
- **A Spark dies**: until the node is NotReady (~40 s) its Caddy/CoreDNS pods stay in the Services, so some
  connections through the surviving Spark still fail; the replica isn't rescheduled (one per Spark, anti-affinity).
- **Tailnet**: clients that resolved to the dead Spark's Tailscale IP hang until their DNS answer expires (TTL 30 s)
  and Tailscale asks the other nameserver.
- Drill: `kubectl -n kube-system delete pod -l app.kubernetes.io/name=kube-vip --field-selector spec.nodeName=<holder>`
  while probing the VIP from the Air (decision 0007 has the probe loop's results).

## Renew the wildcard cert (before December 2027)

As in [web-https.md](web-https.md), then refresh the Secret from SOPS (never printed):

```bash
cd ~/homelab-wt/<branch> && export PATH=$HOME/.local/bin:$PATH
python3 - <<'PY' | sops --encrypt --input-type yaml --output-type yaml \
    --filename-override cluster/platform/edge/web-tls.enc.yaml /dev/stdin > cluster/platform/edge/web-tls.enc.yaml
import json, subprocess
d = json.loads(subprocess.run(["sops", "-d", "--output-type", "json", "secrets/pki.enc.yaml"],
                              capture_output=True, text=True, check=True).stdout)
ind = lambda s: "\n".join("    " + l for l in s.strip().split("\n"))
print("apiVersion: v1\nkind: Secret\nmetadata:\n  name: web-tls\n  namespace: edge\ntype: kubernetes.io/tls\nstringData:")
print("  tls.crt: |\n" + ind(open("hosts/files/pki/web.crt").read()) + "\n  tls.key: |\n" + ind(d["pki_web_key"]))
PY
```

Merge, then `kubectl -n edge rollout restart deploy/edge-caddy` (the Secret's name doesn't change, so the pods
don't roll on their own; Caddy reads the files at start).

## Known issues

- **UDP from Docker containers to k3s Services was dropped** (fixed 2026-11-15): a bad outer VXLAN checksum on
  `flannel.1`, on every node, not just the Dell. Fixed by the `flannel_offload_fix` role (runbooks/k3s.md, known
  issues). Gatus still checks DNS over TCP; UDP works too now. Verify with
  `sudo docker run --rm --network alerting_default --entrypoint nslookup <ntfy image> grafana.nghodki.ai 192.168.86.11`.
- **The API VIP by IP fails TLS**: `192.168.86.10` isn't in the API server's SANs. Use `k8s.nghodki.ai`, or add the
  VIP to `k3s_tls_san` (k3s restarts: one Spark at a time, etcd healthy in between, runbooks/k3s.md).
- **Router DNS must not point at the VIP** while CoreDNS forwards to `192.168.86.1` (a loop; `loop` stops CoreDNS).
  If LAN-only devices should resolve `nghodki.ai` one day, switch the upstream to public resolvers first.

## Cutover

Done on 2026-11-15 (PR #79); kept as the record of how. The old door it falls back to was retired the same day,
so its rollback below no longer applies ([Rollback](#rollback)).

**Preconditions (agent):** this PR merged; `kubectl get applications -n argocd` shows `edge`, `kube-vip`,
`kube-state-metrics` Synced/Healthy; Gatus group `edge` green; `compare-front-doors.sh` `RESULT: same` from dgx-1 and,
LAN and tailnet, from the Air; `edge-zone.py diff-dnsmasq ~/edge-gateway/dnsmasq/dnsmasq.conf` the same.

1. **User, Tailscale admin console → Access controls.** Apply `policies/tailscale/policy.hujson` from the cutover
   PR (the agent prepares it): the family/guests grant and the fleet-devices DNS/web grant get `dst: ["dgx-1",
   "dgx-2"]` instead of `["dgx-1"]` (same ports: `tcp:80`, `tcp:443`, `tcp:53`, `udp:53`), and the tests gain
   `dgx-2:443` accepts for the family and guest users. Harmless on its own: dgx-2 already serves the same door.
2. **User, Tailscale admin console → DNS → Nameservers.** For the split-DNS domain **`nghodki.ai`**, add
   **`100.124.175.23`** as a second nameserver (keep `100.65.137.82`). Delete the separate `model.nghodki.ai` split-DNS
   entry (the `nghodki.ai` one covers it), or add `100.124.175.23` to it too. From here on, clients ask either
   nameserver: dgx-2 answers with the new door, dgx-1's dnsmasq with the old one; both serve the same routes.
   Agent checks from the Air: `tailscale dns status` lists both; `for i in $(seq 20); do dig +short
   grafana.nghodki.ai; done | sort | uniq -c` shows answers from both.
3. **Agent, PR "P3.3 cutover"** (gated merge; Argo CD applies it within ~3 min; observe/alerting deployed from the
   rebased tree):
   - `edge-dns-tailnet` and `edge-caddy-tailnet`: `externalIPs: [100.65.137.82, 100.124.175.23]`. kube-proxy on dgx-1
     then DNATs dgx-1's Tailscale IP `:53/:80/:443` into the cluster ahead of dnsmasq and edge-caddy (their sockets
     stay open, unused, for the rollback). **This is the moment the tailnet moves.**
   - `cluster/platform/cluster-dns/coredns-custom.yaml`: `forward . 10.43.0.53` (pods get the LAN view: the VIP).
   - Gatus: the `web` group's front-door checks go to `192.168.86.11` instead of `.44`; one check stays on `.44:80`
     (Host `model.nghodki.ai`) for the edge-caddy relay. vmalert `KubeVipDown` and `EdgeFrontDoorDown` → critical.
   - Docs: this section's status, architecture §4.1, web-https.md.
4. **Agent, verify:** `.github/scripts/verify-cutover.sh` on dgx-1 and, with `-r`, on the Air (streamed as in
   "Checks"); both must end `CUTOVER VERIFIED`. It checks that both Tailscale IPs answer from the cluster (one
   Tailscale IP per answer, AAAA NOERROR/empty, other zones REFUSED, which edge-dnsmasq would forward), every route
   on dgx-1's Tailscale IP against the old door on its LAN IP, the client's own MagicDNS resolution end to end, and on
   dgx-1: kube-dns → edge-dns (VIP answers), both Services' externalIPs, the apps, Argo CD's Pocket ID redirect, Gatus.
   Before the cutover it fails on exactly those dnsmasq checks (tested).
5. **User:** from a family device, Home Assistant and Open WebUI open; ntfy alerts still arrive.
6. **Agent, a day later:** a failover drill on the tailnet path (delete the CoreDNS and Caddy pods on one Spark,
   probe from the Air through MagicDNS) and record it in decision 0007.

**Router (user):** nothing to change. Optional check in the Google Home app (Wi-Fi → Settings → Advanced networking →
LAN / DHCP IP range): the pool should start at `.20` or above (the default is `.20`–`.250`), so `.10` and `.11` are
never leased. If it starts lower, move its start to `.20`, or reserve `.10` and `.11` for an unused MAC. Don't set the
router's DNS to the VIP (see Known issues).

**Rollback of the cutover** (as it was until 2026-11-15): there is no fast way back to the old door any more. edge-caddy,
edge-dnsmasq and nginx-gateway are stopped, and the new door has no relay to fall back on. See [Rollback](#rollback).

**API VIP:** nothing at the cutover. Kubeconfigs can move to `https://k8s.nghodki.ai:6443` any time (LAN: the VIP;
tailnet: a Spark's Tailscale IP; both in the cert by name).

## Rollback

Since 2026-11-15 the old door is stopped, so the instant rollbacks of the cutover (revert, or drop dgx-1's Tailscale
IP from the Services, with dnsmasq and edge-caddy still listening) are gone. In order of preference:

1. **A bad route or config: revert in Git.** Revert the PR on `main` (gated merge); Argo CD rolls the Caddy/CoreDNS
   pods within ~3 minutes. For the relay retirement (model, dgxmanager, ha direct) that brings back the relay routes,
   so do step 3 as well, or the model plane, dgxmanager and ha fail (502).
2. **One backend unreachable from the pods** (DGXMM after a Docker change, HA after a trusted-proxy change): fix the
   backend side (DGXMM's `.env` bind/trusted proxies, HA's trusted proxies; see "How it works"); the Caddyfile stays.
3. **The old door back on dgx-1** (the cluster's Caddy or CoreDNS broken, or step 1 needs the relay). The containers
   still exist and their config files are where they were; a root-only (0600) copy is
   `~/backups/edge-gateway-2026-11-15.tgz` (kept until 2026-11-22: `~/edge-gateway`, `~/voice-assistant/nginx`,
   `docker inspect` of the three containers, `docker save` of `edge-dnsmasq:local`):
   ```bash
   # if the files are gone (only the home/ paths; the rest is the inspect JSON and the image tar):
   #   sudo tar -C / -xzf ~/backups/edge-gateway-2026-11-15.tgz home
   for c in nginx-gateway edge-caddy edge-dnsmasq; do docker update --restart unless-stopped $c; done
   docker start nginx-gateway edge-caddy edge-dnsmasq
   ```
   nginx-gateway reaches DGXMM on the Docker network, which DGXMM still trusts only if `172.23.0.0/16` is back in
   `DGXMM_TRUSTED_PROXIES` (it was removed after the retirement; the `.env` backup is `/root/backups/dgxmm-env-20261115-192847`).
   edge-caddy then serves dgx-1's LAN IP again; the tailnet stays on the cluster (kube-proxy owns dgx-1's Tailscale
   IP :53/:80/:443) until the cutover is reverted too: revert #79 or drop `100.65.137.82` from the two tailnet
   Services (`kubectl -n edge patch svc edge-caddy-tailnet --type merge -p '{"spec":{"externalIPs":["100.124.175.23"]}}'`,
   the same for `edge-dns-tailnet`, after turning off auto-sync as in the cutover rollback in Git history). If the
   cluster API is down, put the old door ahead of kube-proxy:
   `sudo iptables -t nat -I PREROUTING 1 -d 100.65.137.82 -p tcp -m multiport --dports 80,443 -j DOCKER`, and
   `-p udp --dport 53 -j ACCEPT` / `-p tcp --dport 53 -j ACCEPT` at positions 2 and 3.
   The relay itself (Caddy pods → `192.168.86.44:80` → edge-caddy → nginx-gateway) is the Caddyfile before PR
   "retire the edge relay" (`git log -- cluster/platform/edge/caddy/Caddyfile`).
4. **User**, if dgx-2 or the cluster is broken: remove `100.124.175.23` from the `nghodki.ai` nameservers in the
   Tailscale admin console.

After 2026-11-22 (a week without a rollback) the containers and `~/edge-gateway` can be deleted; the tarball stays in
`~/backups` until then and goes with them.
