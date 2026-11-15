# k3s cluster (plan P3.2)

Built over Wi-Fi before the Sparks get Ethernet: [decision 0005](../decisions/0005-k3s-over-wifi.md). Layout:
architecture §4.4 and §5. Ansible: role `k3s`, `hosts/playbooks/k3s.yml`, inventory groups `k3s_servers`,
`k3s_agents` and `k3s_init` (dgx-2).

## Versions

| Piece | Version |
|---|---|
| k3s | **v1.37.2+k3s1** (stable channel, 2026-11-03). Binary and `install.sh` pinned by sha256 in `roles/k3s/defaults/main.yml` |
| Kubernetes | v1.37.2 |
| etcd (embedded) | 3.7.1 |
| containerd (k3s's own, `/run/k3s/containerd`) | 2.3.7-k3s1 |

## Nodes

| Node | Role | Node IP / interface | External IP | Labels | Taint |
|---|---|---|---|---|---|
| dgx-2 | server + etcd (started the cluster, `cluster-init`) | 10.100.136.2 `enp1s0f0np0` (cable) | 192.168.86.36 | `nghodki.ai/role=gpu`, `nghodki.ai/hw=gb10` | none |
| dgx-1 | server + etcd | 10.100.136.1 `enp1s0f0np0` (cable) | 192.168.86.44 | `nghodki.ai/role=gpu`, `nghodki.ai/hw=gb10` | none |
| jetson | etcd only (no API server, controller manager or scheduler) + kubelet | 192.168.86.211 `wlP1p1s0` (Wi-Fi) | — | `nghodki.ai/role=edge-robot`, `nghodki.ai/hw=orin` | `nghodki.ai/jetson=true:NoSchedule` |
| omarchy | agent | 192.168.86.49 `wlp1s0` (Wi-Fi) | — | `nghodki.ai/role=agent-node`, `nghodki.ai/hw=x86` | none |

- Node names are the inventory names (`node-name`), not the hostnames. `node.kubernetes.io/instance-type` is `k3s`
  (set by k3s's cloud controller), so hardware is in `nghodki.ai/hw`.
- Labels and taints in `node-label`/`node-taint` are applied when a node **registers**. To change them on a live
  node, use `kubectl label` / `kubectl taint` as well as the vars.
- The Jetson and Omarchy have `/32` routes to 10.100.136.1 via 192.168.86.44 and 10.100.136.2 via 192.168.86.36 on
  their NetworkManager connection `nikghodki_wifi` (`nmcli -g ipv4.routes connection show nikghodki_wifi`).
  The role checks that `rp_filter` isn't strict on every node's LAN interface (all are 2, loose).
- Omarchy's ufw allows 10250/tcp and 8472/udp from 192.168.86.0/24 and 10.100.136.0/24, and pod traffic in and
  through `cni0` and `flannel.1`.
- Pod CIDR 10.42.0.0/16, services 10.43.0.0/16, flannel VXLAN (MTU 1450).
- Disabled: traefik, servicelb (80/443 belong to edge-caddy on dgx-1), metrics-server. Kept: CoreDNS,
  local-path storage. Secrets encryption at rest is on.
- Kubelet reservations: Sparks `system-reserved=cpu=2,memory=8Gi`, `kube-reserved=cpu=1,memory=2Gi` (scheduling
  budget only; the DGXMM engines run in Docker and the kubelet doesn't count them). Jetson
  `system-reserved=cpu=1500m,memory=4Gi`, `kube-reserved=cpu=500m,memory=768Mi`, eviction at 300 MiB available,
  `max-pods=40` (about 2.3 GiB allocatable). Omarchy `system-reserved=cpu=1,memory=2Gi`, `kube-reserved=cpu=250m,memory=512Mi`.

Files on each node: `/etc/rancher/k3s/config.yaml` (from `roles/k3s/templates/config.yaml.j2`, no secrets),
`/etc/rancher/k3s/token` (0600), units `k3s.service` (servers) / `k3s-agent.service` (Omarchy), and
`/usr/local/bin/k3s-killall.sh`, `k3s-uninstall.sh` / `k3s-agent-uninstall.sh` from the pinned `install.sh`.

## Access

- **dgx-1:** `kubectl` as `nikghodki-dgx` uses `~/.kube/config` (0600, admin, server `https://192.168.86.44:6443`;
  `/etc/profile.d/homelab-kubeconfig.sh` sets `KUBECONFIG`). Not in Git.
- **`k8s.nghodki.ai`** resolves to both Sparks (LAN and Tailscale IPs) in edge-dnsmasq and is in the API cert's
  SANs. Go programs (kubectl) on the fleet can't use it yet: edge-dnsmasq answers AAAA with NXDOMAIN, which Go
  treats as "no such host". kube-vip (P3.3) replaces this with one floating IP.
- The join token is in `secrets/k3s.enc.yaml` (`k3s_token`), in the full `K10<ca-hash>::server:<secret>` form,
  so joining nodes check the cluster CA. Never print it.
- Anonymous API access is off: `curl -k https://192.168.86.44:6443/readyz` answers 401 when the API server is up.

## Health

```bash
kubectl get nodes -o wide
kubectl get --raw /readyz; kubectl get --raw /healthz/etcd
kubectl get nodes -o custom-columns='N:.metadata.name,VOTER:.status.conditions[?(@.type=="EtcdIsVoter")].status'
```

etcd membership (k3s doesn't ship etcdctl; use the etcd release's `etcdctl`, checksum-verified, on a server):

```bash
C=/var/lib/rancher/k3s/server/tls/etcd
sudo etcdctl --endpoints https://10.100.136.1:2379,https://10.100.136.2:2379,https://192.168.86.211:2379 \
  --cacert $C/server-ca.crt --cert $C/client.crt --key $C/client.key endpoint status -w table   # or: member list
```

Monitoring: Gatus group `k3s` (API on both Sparks, TCP 2379 to every member), vmalert `K3sEtcdMemberDown`,
`K3sEtcdQuorumLost` and `K3sApiDown` (`hosts/stacks/observe/vmalert/rules/k3s.yml`).

Quorum is 2 of 3. Losing one member of any kind is fine. Losing a Spark **and** the Jetson (Wi-Fi) stops the API;
running pods and all Docker services keep running. A GPU/unified-memory OOM can take a Spark down (it happened on
2026-11-15), so don't take the Jetson out of etcd casually.

## Docker on the Sparks

k3s runs its own containerd; Docker and its iptables chains are untouched (kube-proxy and flannel add their own chains
in front of `DOCKER-USER`). k3s binds no LAN-IP ports: the API server listens on `*:6443`, the kubelet on `*:10250`,
etcd on the node IP (the cable on the Sparks). So a late Wi-Fi after a reboot doesn't affect k3s; restarting
containers that publish on a LAN IP is a Docker matter. Before and after any k3s change check `docker ps`, Gatus and
`curl http://127.0.0.1:4000/health/liveliness` on dgx-1.

## Change, upgrade

```bash
source ~/.venvs/ansible/bin/activate && cd ~/homelab/hosts
ansible-playbook playbooks/k3s.yml --check --diff
ansible-playbook playbooks/k3s.yml            # dgx-2, then dgx-1 and the Jetson one at a time, then Omarchy
```

A config, token or binary change restarts k3s on that node. **Upgrade:** set `k3s_version`, `k3s_sha256` (from
`sha256sum-arm64.txt` / `sha256sum-amd64.txt` in the release) and `k3s_install_script_sha256` (`install.sh` at the
new tag). One minor version at a time. Take a snapshot first.

## Add a node

1. Inventory: add it to `k3s_servers` or `k3s_agents`. In `host_vars`: `k3s_role`, `k3s_node_ip`, `k3s_lan_iface`,
   `k3s_flannel_iface`, labels/taints, kubelet reservations; `k3s_link_routes` if it isn't on the Spark cable;
   `k3s_ufw: true` if ufw is on.
2. `ansible-playbook playbooks/k3s.yml --limit <node> --check --diff`, then without `--check`.
3. Servers: check the etcd member list shows it as a voter. Keep an odd number of etcd members.

## Remove or roll back a node

1. `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data` (servers and agents).
2. `kubectl delete node <node>`. For an etcd member, k3s's etcd controller removes the member as well; check with
   `etcdctl member list` and, if it's still there, `etcdctl member remove <id>`. Do this **before** uninstalling, so
   the remaining members don't wait for it.
3. On the node: `sudo /usr/local/bin/k3s-uninstall.sh` (servers, incl. the Jetson) or
   `sudo /usr/local/bin/k3s-agent-uninstall.sh` (Omarchy). That removes k3s, its data and its iptables rules; Docker
   is not touched. The `/32` routes stay on the NetworkManager connection (harmless); remove them with
   `nmcli connection modify nikghodki_wifi -ipv4.routes "10.100.136.1/32 192.168.86.44"` (and `.2`) if wanted.
4. Remove it from the k3s inventory groups. Never let etcd stay at 2 members for long.

dgx-2 has `cluster-init: true`. If dgx-2 itself is rebuilt from scratch, set `k3s_cluster_init: false` on it (it
joins `https://10.100.136.1:6443`) and point `k3s_server_url` at dgx-1, or it would start a second cluster.

## Snapshots

k3s takes etcd snapshots on every server (including the Jetson) at 00:00 and 12:00 and keeps 5, in
`/var/lib/rancher/k3s/server/db/snapshots/` (0600 root). Manual: `sudo k3s etcd-snapshot save --name <name>`;
list: `sudo k3s etcd-snapshot list`. **Off-host backup is off** ([decision 0002](../decisions/0002-backups-off-for-now.md));
snapshots to SeaweedFS on dgx-2 are P3.8. Restore (whole cluster): stop k3s on every server, on one server
`sudo k3s server --cluster-reset --cluster-reset-restore-path=<snapshot>`, then start it, wipe
`/var/lib/rancher/k3s/server/db` on the other servers and start them so they re-join.

## Moving to wired Ethernet (P0.11)

See decision 0005. The Spark-to-Spark settings don't change. Update the Sparks' `k3s_node_external_ip`,
`k3s_lan_iface` (`enP7s7`), `k3s_tls_san`, the `via` addresses in `k3s_link_routes`, `k8s.nghodki.ai` and the Gatus
checks; then roll one node at a time (agents, Jetson, dgx-1, dgx-2), checking nodes and the etcd member list between
each. A changed node IP on the Jetson means remove-and-rejoin (above).

## Not installed yet (on purpose)

| What | Plan |
|---|---|
| kube-vip floating IP; DNS + HTTPS proxy in the cluster | P3.3 |
| Argo CD (and SOPS in the cluster) | P3.4 |
| Kyverno | P3.5 |
| Tetragon | P3.6 |
| NVIDIA device plugin / GPU operator: **the cluster doesn't touch the GPUs** (k3s registers an `nvidia` containerd runtime, but nothing requests GPUs) | after the DGXMM work |
| Workloads (LiteLLM, NATS, Postgres, observability, ...) | P3.7 |
| Off-host etcd snapshots | P3.8 |
| metrics-server, an Ingress controller, ServiceLB | not planned for now |
