# The front door: `*.nghodki.ai` DNS and HTTPS (plan P3.3)

Design and test results: [decision 0007](../decisions/0007-edge-in-cluster.md). Certificates: [web-https.md](web-https.md).

**Status: cut over (P3.3).** The tailnet (every client) uses the in-cluster door on both Sparks' Tailscale IPs; the
LAN view is on the VIP. edge-caddy on dgx-1 stays as the relay to nginx-gateway and, with edge-dnsmasq (its sockets
are still open but no longer reached on dgx-1's Tailscale IP), as the [rollback](#cutover).

| | Old door (relay + rollback) | New door (k3s, live) |
|---|---|---|
| DNS | edge-dnsmasq: `192.168.86.44:53` (dgx-1's Tailscale IP is the cluster's since the cutover) | `edge/edge-dns` (CoreDNS, 2 replicas): VIP `192.168.86.11:53` (LAN view), both Sparks' Tailscale IPs `:53` (tailnet view) |
| HTTPS | edge-caddy: dgx-1's LAN IP `:80/443` (the nginx-gateway relay) | `edge/edge-caddy` (Caddy, 2 replicas): VIP `192.168.86.11:80/443`, both Sparks' Tailscale IPs `:80/443` |
| Floating IPs | none | kube-vip (`kube-system`, DaemonSet on the Sparks): `192.168.86.10` (k3s API), `192.168.86.11` (edge) |
| Config | `~/edge-gateway/conf/Caddyfile`, `dnsmasq/dnsmasq.conf` (not in Git) | `cluster/platform/edge/`: `names.txt` (every name), `caddy/Caddyfile`, generated `coredns/*.db`, `web-tls.enc.yaml` |
| Argo CD apps | | `kube-vip`, `edge`, `kube-state-metrics` (project `platform`) |

## How it works

- **LAN**: `*.nghodki.ai` → `192.168.86.11`, which kube-vip keeps on one Spark's `wlP9s9` (gratuitous ARP; measured
  failover 0 s graceful, 14 s when the holder dies). kube-proxy on that Spark DNATs it to the CoreDNS/Caddy pods.
  Nothing uses LAN DNS today (the router doesn't forward `nghodki.ai`), so this view is for fleet hosts and later.
- **Tailnet** (every client today): Tailscale split DNS for `nghodki.ai` → the Sparks' Tailscale IPs. Each CoreDNS
  replica answers with **its own Spark's** Tailscale IP (zone `tailnet-<node>.db`, TTL 30 s), so an answer never names
  a dead Spark; Caddy on either Tailscale IP reaches either Caddy pod. Non-`nghodki.ai` queries are REFUSED there.
- **Not through Caddy**: `nats`, `fleet` (dgx-1), `backup` (dgx-2), the host names (`jetson`, `pi`, ...) and
  `k8s` (the API VIP on the LAN; on the tailnet, the answering Spark's Tailscale IP).
- **nginx-gateway** (model, dgxmanager, ha, the default route) is reachable only on dgx-1's Docker
  network, so Caddy sends those to edge-caddy on `192.168.86.44:80`, which relays to nginx-gateway. edge-caddy stays
  until those services move into the cluster (P3.7).

## Add or change a route

**Since the cutover, only the in-cluster door** (steps 1–3 and 5). Step 4 (the old door) is needed only for a route
behind nginx-gateway, or to keep the rollback complete:

1. A new name: add `<name>  edge` (or a host target, see the file's header) to `cluster/platform/edge/names.txt`, then
   `.github/scripts/edge-zone.py generate` (writes the zones; CI runs `check`).
2. The route: add a `@<name> host <name>.nghodki.ai` / `handle` block to `cluster/platform/edge/caddy/Caddyfile`
   (inside `(nghodki_routes)`, so it's on :80 and :443). Backends are LAN IPs and ports, a Service name, or, for
   something only on dgx-1's Docker network, `192.168.86.44:80`.
3. PR, gated merge; Argo CD rolls the pods (the ConfigMaps are hashed) within ~3 minutes.
4. Old door, by hand on dgx-1: the same block in `~/edge-gateway/conf/Caddyfile` (back it up first), the
   `address=` lines from `.github/scripts/edge-zone.py dnsmasq` into `~/edge-gateway/dnsmasq/dnsmasq.conf`, then
   `docker restart edge-caddy edge-dnsmasq`. Check with `edge-zone.py diff-dnsmasq ~/edge-gateway/dnsmasq/dnsmasq.conf`.
5. `.github/scripts/compare-front-doors.sh` on dgx-1 must say `RESULT: same`.



## Checks

```bash
cd ~/homelab && .github/scripts/compare-front-doors.sh                      # LAN: VIP vs dgx-1, every route + DNS
.github/scripts/compare-front-doors.sh -n 100.124.175.23 -o 100.65.137.82 -v tailnet   # tailnet path
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

Monitoring: Gatus group `edge` on the Dell (DNS on the VIP and on dgx-2's Tailscale IP over TCP, Caddy on the VIP with
the cert's expiry, grafana through the VIP, the API VIP); vmalert `front-door` (`KubeVipNotReady`, `KubeVipDown`,
`EdgeReplicasDown`, `EdgeFrontDoorDown`, `KubeStateMetricsDown`) from kube-state-metrics at `10.43.0.120`.

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
- **X-Forwarded-For for nginx-gateway routes** is the Caddy pod's node, not the client: edge-caddy overwrites it.
- **Router DNS must not point at the VIP** while CoreDNS forwards to `192.168.86.1` (a loop; `loop` stops CoreDNS).
  If LAN-only devices should resolve `nghodki.ai` one day, switch the upstream to public resolvers first.

## Cutover

Not done. Needs approval. Everything before step 3 is reversible without touching the cluster.

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

**Rollback:**

- *Normal* (Argo CD and the API up): revert the cutover PR on `main`. Within ~3 minutes the externalIP is gone and
  dnsmasq and edge-caddy, which never stopped listening, get dgx-1's tailnet traffic again; pods forward to
  `192.168.86.44` again.
- *Fast* (seconds): stop Git from undoing it, then drop dgx-1's Tailscale IP from the two Services:
  ```bash
  export KUBECONFIG=~/.kube/config
  kubectl -n argocd patch application root --type json -p '[{"op":"remove","path":"/spec/syncPolicy/automated"}]'
  kubectl -n argocd patch application edge --type json -p '[{"op":"remove","path":"/spec/syncPolicy/automated"}]'
  for s in edge-dns-tailnet edge-caddy-tailnet; do
    kubectl -n edge patch svc $s --type merge -p '{"spec":{"externalIPs":["100.124.175.23"]}}'; done
  ```
  Then revert the PR, and give the apps back to Git: `kubectl apply -f ~/homelab/cluster/bootstrap/apps/root.yaml`.
- *Cluster API down* (can't patch): on dgx-1, put the old door in front of kube-proxy's rules (kube-proxy doesn't
  move its jump once it exists), and delete these again when the cluster is back:
  ```bash
  sudo iptables -t nat -I PREROUTING 1 -d 100.65.137.82 -p tcp -m multiport --dports 80,443 -j DOCKER
  sudo iptables -t nat -I PREROUTING 2 -d 100.65.137.82 -p udp --dport 53 -j ACCEPT
  sudo iptables -t nat -I PREROUTING 3 -d 100.65.137.82 -p tcp --dport 53 -j ACCEPT
  ```
- *User*, if dgx-2 or the cluster is broken: remove `100.124.175.23` from the `nghodki.ai` nameservers (step 2). The
  policy grants can stay.

**API VIP:** nothing at the cutover. Kubeconfigs can move to `https://k8s.nghodki.ai:6443` any time (LAN: the VIP;
tailnet: a Spark's Tailscale IP; both in the cert by name).
