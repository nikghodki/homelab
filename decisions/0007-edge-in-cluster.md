# 0007: The front door in k3s: kube-vip ARP on Wi-Fi, CoreDNS + Caddy in `edge`, the tailnet via the Sparks' Tailscale IPs

- Date: 2026-11-15
- Status: decided (nikghodki); built and tested in parallel; cutover approved and applied in the P3.3 cutover PR ([runbooks/edge.md](../runbooks/edge.md#cutover))

## Context

Plan P3.3 moves `*.nghodki.ai` (DNS and the HTTPS front door) from Docker on dgx-1 (`~/edge-gateway`: `edge-dnsmasq` and
`edge-caddy`) into k3s, so a single Spark failing doesn't take every web UI down (architecture §3.1, §4). The
constraints that shaped it, all measured on 2026-11-15:

- **The Sparks are Wi-Fi clients** (`wlP9s9` on a Nest Wifi Pro). Floating IPs need the access point to accept a
  station announcing an extra IP with gratuitous ARP, and to move it.
- **Every client resolves `nghodki.ai` through Tailscale split DNS** (to dgx-1's Tailscale IP). The router answers
  NXDOMAIN for it, so nothing uses LAN DNS. Tailscale clients can't reach a LAN VIP without a subnet route.
- **Ports in use on dgx-1:** edge-caddy (docker-proxy) on `0.0.0.0:80/443`, edge-dnsmasq on `192.168.86.44:53` and
  `100.65.137.82:53`. On dgx-1, `nat PREROUTING` jumps to `KUBE-SERVICES` before `DOCKER` (kube-proxy keeps its jump
  first), so a kube-proxy DNAT for an address takes that address from Docker and dnsmasq before they see a packet.
- **nginx-gateway** (model, dgxmanager, ha, the default route) has no published port: it is only on
  dgx-1's Docker network `gateway`.
- **A dead Tailscale peer blackholes connections.** From the MacBook Air, `curl --resolve host:443:<offline peer>,<live
  Spark>` took **75 s** (curl's connect timeout) before it tried the second address. Answering with both Sparks'
  Tailscale IPs would hang half the connections whenever a Spark is down.
- Memory: the Sparks are near their limits from model work; keep everything small and limited.

## Decision

- **kube-vip v1.3.1, ARP mode, DaemonSet on the two Sparks** (`kube-system`, hostNetwork, `NET_ADMIN`/`NET_RAW`, not
  privileged; kube-system is already in Kyverno's host-namespace allowlist). Two VIPs on `wlP9s9`, each on the
  leader of its own lease (10 s lease, 7 s renew deadline, 2 s retry):
  - **`192.168.86.10`: k3s API** (`plndr-cp-lock`). `k8s.nghodki.ai` on the LAN.
  - **`192.168.86.11`: edge** (`plndr-svcs-lock`): LoadBalancer Services `edge-dns-lan` (53) and `edge-caddy-lan`
    (80/443) share it. No NodePorts (`allocateLoadBalancerNodePorts: false`).
  - Both are below the Nest's default DHCP pool (`.20`–`.250`); nothing answered on `.2`–`.19` (ping/ARP sweep).
- **Tailnet: the Sparks' Tailscale IPs, not a subnet route.** Services `edge-dns-tailnet` and `edge-caddy-tailnet`
  carry the Sparks' Tailscale IPs as `externalIPs`, so kube-proxy on each Spark DNATs its own Tailscale IP's
  :53/:80/:443 to the pods. Tailscale split DNS lists **both Sparks' Tailscale IPs**. Each CoreDNS replica answers
  tailnet queries with **its own Spark's Tailscale IP** (`tailnet-${NODE_NAME}.db`), so every answer names a Spark
  that is up, and Caddy on either Spark's Tailscale IP reaches either Caddy pod. TTL 30 s.
  Why not a subnet route for the VIP: it adds a dependency on ARP failover *and* on Tailscale's subnet-router
  failover, needs route approval and `--accept-routes` on every Linux client (off on the fleet hosts), and sends
  on-LAN Tailscale devices through a router hop. The Tailscale IPs never move, need no ARP and work on every client
  as it is.
  **Until the cutover only dgx-2's Tailscale IP is listed**; dgx-1's 100.65.137.82 is today's front door, and listing
  it is the cutover itself (a DNAT that takes it over from dnsmasq and edge-caddy).
- **CoreDNS (namespace `edge`, `edge-dns`, 2 replicas, one per Spark)**, separate from k3s's cluster DNS. The `file`
  plugin serves zones generated from one list, `cluster/platform/edge/names.txt` (`.github/scripts/edge-zone.py`;
  CI fails if the zones are stale). Authoritative, so **AAAA for an existing name is NOERROR with no answer** and an
  unknown name is NXDOMAIN. LAN view on :1053 (behind the VIP:53) forwards everything else to 192.168.86.1 (`loop`
  guards against the router ever forwarding back); the tailnet view on :1054 answers only `nghodki.ai` (REFUSED
  otherwise, so it's not an open resolver on the tailnet). The same list reproduces edge-dnsmasq's 51 records
  exactly (`edge-zone.py diff-dnsmasq`).
- **Caddy 2.11.9 (`edge-caddy`, 2 replicas, one per Spark)** with a Git-managed Caddyfile that mirrors edge-caddy's
  routes, including the http→https redirects (id, ops, mlflow, temporal, argocd), the `ca.nghodki.ai` file server
  (a ConfigMap copy of `hosts/files/web-ca`, checked by CI). Differences, all forced by
  running in a pod: nginx-gateway's routes go through edge-caddy on dgx-1 (`192.168.86.44:80`), which hands them to
  nginx-gateway; Argo CD by Service name. The wildcard cert and key are the TLS Secret `edge/web-tls` (KSOPS,
  `web-tls.enc.yaml`). Non-root, read-only root filesystem, no capabilities: :80/:443 via the namespaced sysctl
  `net.ipv4.ip_unprivileged_port_start=0`.
- **kube-state-metrics v2.20.0** (`kube-system`, fixed ClusterIP `10.43.0.120:8080`, scraped by VictoriaMetrics on
  dgx-2) for the readiness alerts. Restricted to pods, deployments, daemonsets, statefulsets, replicasets, nodes.
- **Kyverno:** `edge` stays out of the admission webhooks, like `kube-system` and `argocd`, so the front door can be
  rescheduled while Kyverno is down. Background scans still report on it. Its pods passed every policy (`kyverno
  apply` on the live pods: 33 pass, 0 fail). CoreDNS needs `NET_BIND_SERVICE` (the image sets that file capability on
  `/coredns`; without it in the bounding set, exec fails with EPERM).
- **CrowdSec waits.** It's a LAPI plus a Caddy bouncer (a custom Caddy build) and a log pipeline; nothing reaches the
  front door from outside the LAN and tailnet today. Revisit if anything is ever exposed publicly.

## Test results (2026-11-15, before any cutover; clients unchanged)

**Routes** (`.github/scripts/compare-front-doors.sh`: every `edge` name over http and https, old vs new, status code
and redirect target without its query string). Every row matched from dgx-1, the Dell, the Jetson and the MacBook
Air over the LAN (new = the VIP), and from the Air over Tailscale (old = dgx-1's Tailscale IP, new = dgx-2's):

| Route | http | https |
|---|---|---|
| model | 404 | 404 |
| litellm-admin, controlcenter, webui, ha, ntfy, ca, phoenix | 200 | 200 |
| dgxmanager | 302 → /dgxmm/ | 302 → /dgxmm/ |
| coolify | 302 → /login | 302 → /login |
| grafana | 302 → /login | 302 → /login |
| status | 302 → Pocket ID | 302 → Pocket ID |
| id, temporal, argocd | 308 → https | 200 |
| ops, mlflow | 308 → https | 302 → Pocket ID |

**DNS**: all 27 names (26 after voice-agent was retired) returned the zone's A records, AAAA NOERROR/0 answers, `no-such-name` NXDOMAIN, on the LAN
view (VIP) and the tailnet view (dgx-2's Tailscale IP; 20 queries from the Air: 11 answered dgx-2, 9 dgx-1).

**ARP failover over Wi-Fi works.** The Air (a LAN client that is not a node; the Dell and the Jetson are nodes, so
their own kube-proxy answers for the VIP without ARP) probed `http://ca.nghodki.ai` and DNS on the VIP every ~0.35 s:

| Test | Result |
|---|---|
| Graceful: delete the leader's kube-vip pod | 216 probes, **0 failed**; the Air's ARP entry moved to dgx-2's MAC |
| Hard: on the leader, `SIGSTOP` kube-vip and drop VIP traffic on `wlP9s9` (a dead node) | **14.2 s** gap (lease 10 s + retry + gratuitous ARP), then served by dgx-1 |
| Resume the frozen kube-vip | one 1.5 s blip while it re-announced before noticing it had lost the lease (then it restarted itself); a crashed node doesn't come back half-alive like this |

API VIP: `https://192.168.86.10:6443/readyz` answered 401 from the Air; kubectl by name (`--tls-server-name
k8s.nghodki.ai`) works; by bare IP it fails TLS (the VIP isn't in the serving cert's SANs; adding it to `k3s_tls_san`
needs a rolling k3s restart, not done).

**Not tested yet:** a real Spark loss (its Caddy/CoreDNS endpoints stay in the Services until the node is NotReady,
~40 s, so some connections through the *surviving* Spark still pick the dead pods until then), and Tailscale's
behaviour with two split-DNS nameservers when one is dead (needs the admin-console change; cutover step).

**Memory** (cgroup working set, 2026-11-15): kube-vip 12 + 9 MiB, edge-dns 11 + 32 MiB, edge-caddy 14 + 14 MiB,
kube-state-metrics 13 MiB: **~105 MiB** in total. Requests 240 Mi, limits 960 Mi.

**Retired since** (2026-11-15, by the user, on both doors): `voice-agent.nghodki.ai` (its Caddy site and DNS
records; the comparison now covers 17 routes and 26 names). Nothing for the retired Jetson vision service was ever
routed. `coolify.nghodki.ai` (its Caddy site and DNS records), with Coolify itself (decision 0010): 16 routes and 25
names.

## Alternatives considered

- **Subnet route for the VIP** (above). Kept as the fallback if per-Spark Tailscale IPs ever misbehave.
- **Both Tailscale IPs in every answer.** Simpler, but the 75 s blackhole on a dead peer (measured) rules it out.
- **hostNetwork CoreDNS/Caddy bound to each Spark's addresses.** Exact per-node control, but host-namespace pods in
  `edge` (Kyverno allowlist) and port fights with edge-caddy/dnsmasq during the parallel phase.
- **A staging VIP or staging ports.** Not needed: the VIP is a new address, and kube-proxy's DNAT on it can't collide
  with edge-caddy's `0.0.0.0` sockets (verified: the VIP served the new door while dgx-1:80/443 kept serving the old).
- **MetalLB (L2).** Same ARP mechanism, an extra controller and speaker, and it can't do the API VIP.

## Consequences

- Clients keep using edge-dnsmasq and edge-caddy until the cutover (runbooks/edge.md "Cutover"); the new door is live
  on the VIP and on dgx-2's Tailscale IP for testing.
- **edge-caddy stays** after the cutover as the relay to nginx-gateway (model, dgxmanager, ha), and as
  the instant rollback. It goes away when those services move into the cluster (P3.7).
- Routes now live in Git (`cluster/platform/edge/caddy/Caddyfile`, `names.txt`). Until the cutover a route change
  goes to both doors (runbooks/edge.md).
- New ClusterIPs `10.43.0.53` (edge-dns LAN; kube-system's CoreDNS can forward `nghodki.ai` there after the cutover)
  and `10.43.0.120` (kube-state-metrics).
- Found on the way: **UDP from Docker containers on the Dell to any k3s Service is dropped** (the Dell's `flannel.1`
  sends NAT'd UDP with a bad outer VXLAN checksum, seen on dgx-2 as `bad udp cksum`; TCP and host-originated UDP are
  fine). Gatus's edge DNS checks use TCP because of it. It will also bite pods on the Dell that use UDP to Services
  on other nodes (DNS!). The usual fix is `ethtool -K flannel.1 tx-checksum-ip-generic off` on the Dell, made
  persistent by Ansible. Not applied here; see runbooks/edge.md "Known issues".

## Relay retired (2026-11-15)

The routes nginx-gateway served (model, dgxmanager, ha, and the door by IP) moved into the in-cluster Caddyfile, to the
real backends: LiteLLM and DGXMM on dgx-1's direct-cable address `10.100.136.1` (DGXMM's published port moved there
from `127.0.0.1`, with the Caddy pods' source addresses `10.100.136.2` and `172.23.0.1` as trusted proxies), Home
Assistant on the Jetson (dgx-2's LAN IP `192.168.86.36` added to its trusted proxies by the user). The voice routes
(`/tts/`, `voice-agent.nghodki.ai`) were dropped (D26). nginx's implicit 1 MB request limit on `/v1/` and Home
Assistant was not carried over; DGXMM's explicit one was. Then edge-caddy, edge-dnsmasq and nginx-gateway were stopped
on dgx-1 (config kept, root-only backup for a week). The instant rollback of the cutover went with them; the rollback
is now a Git revert plus restarting the stopped containers (runbooks/edge.md "Rollback").
