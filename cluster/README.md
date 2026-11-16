# cluster

What Argo CD deploys into k3s (plans P3.4/P3.5, [runbooks/argocd.md](../runbooks/argocd.md),
[decision 0006](../decisions/0006-gitops-platform.md)). Argo CD pulls `git@github.com:nikghodki/homelab.git`
(`main`) with a read-only deploy key every 2 minutes (plus up to 1 minute of jitter); nothing pushes into the cluster.

```
cluster/
├── bootstrap/apps/        root app of apps: one Application per component, plus the AppProjects
│   ├── root.yaml          manages this folder (itself included); applied once by hand at bootstrap
│   ├── projects.yaml      AppProjects `platform` (cluster-wide tooling) and `apps` (namespaced workloads)
│   ├── argocd.yaml        Argo CD manages itself (chart + platform/argocd)
│   ├── kyverno.yaml, kyverno-policies.yaml, cnpg-operator.yaml, cluster-dns.yaml
│   ├── kube-vip.yaml, edge.yaml, kube-state-metrics.yaml   the front door (P3.3, runbooks/edge.md)
│   └── smoke.yaml         SOPS canary (apps/_smoke)
├── platform/<component>/  values.yaml for the Helm chart and extras/ (kustomize: Services, NetworkPolicies, SOPS secrets)
│   ├── argocd/            Argo CD 3.6 + KSOPS in the repo-server
│   ├── kyverno/           Kyverno 1.20, admission (2 replicas) + reports controllers
│   ├── cnpg-operator/     CloudNativePG 1.30 operator, no clusters yet
│   ├── cluster-dns/       CoreDNS zone for *.nghodki.ai (forwards to edge-dns, the in-cluster door)
│   ├── kube-vip/          kube-vip DaemonSet (kube-system, hostNetwork): API VIP .10, edge VIP .11
│   ├── edge/              namespace edge: CoreDNS (names.txt → zones) and Caddy (the *.nghodki.ai front door)
│   └── kube-state-metrics/  readiness metrics for vmalert (kube-system)
└── apps/                  workloads, one folder per app (README.md); `_smoke` is the SOPS canary
```

Kyverno's policies are in [`policies/kyverno`](../policies/kyverno) (app `kyverno-policies`), Enforce since P3.5.

## Rules

- **Pin everything.** Helm charts by version in the Application, images by digest when a manifest here names an
  image (Kyverno refuses third-party images without one). Our own `ghcr.io/nikghodki/*` images may be named by tag:
  Kyverno verifies the signature and writes the digest into the Pod (runbooks/build-sign.md). No `latest`.
- **Requests and limits on every container**, one replica for now, and a `nodeSelector` on
  `nghodki.ai/role: gpu` (Sparks) or `agent-node` (Omarchy). Nothing goes on the Jetson unless it is meant to
  (it is tainted). Kyverno **enforces** signed `ghcr.io/nikghodki` images, limits, tags, registries, digests and no
  privileged pods (runbooks/kyverno.md); check new manifests with `kyverno apply policies/kyverno --resource <dir>`.
- **Secrets** are Kubernetes Secret manifests named `*.enc.yaml`, SOPS-encrypted (`.sops.yaml` encrypts only
  `data`/`stringData` under `cluster/`) and listed in a KSOPS generator (`secret-generator.yaml`). CI fails on a
  plaintext Secret anywhere in `cluster/` (`.github/scripts/check-sops.sh`).
- **CI** (`.github/scripts/check-kubernetes.sh`) runs kubeconform on every manifest here (Helm `values.yaml` and
  `*.enc.yaml` skipped) and the Kyverno CLI with `policies/kyverno`.

## Fixed ClusterIPs for the hosts

Docker services on the nodes (edge-caddy on dgx-1, VictoriaMetrics on dgx-2) reach a few Services directly: kube-proxy
on every node routes ClusterIPs for host and Docker traffic too, so nothing is published on the LAN. These use the
**static band 10.43.0.0–10.43.0.255** of the service CIDR, which the API server doesn't hand out dynamically.

| IP:port | Service | Used by |
|---|---|---|
| 10.43.0.10:53 | kube-dns (k3s; 2 replicas, one per Spark: `cluster-dns/coredns-replicas.ssa-patch.yaml`) | pods |
| 10.43.0.53:53 | `edge/edge-dns-lan` (also on the VIP 192.168.86.11) | kube-system's CoreDNS for `nghodki.ai` |
| 10.43.0.54:4180 | `edge/edge-auth-ip` | edge-caddy's forward auth (no cluster DNS on the door's path) |
| 10.43.0.100:80, :8083 | `argocd/argocd-server-host` | edge-caddy (`argocd.nghodki.ai`), VictoriaMetrics |
| 10.43.0.101:8082 | `argocd/argocd-controller-host` | VictoriaMetrics |
| 10.43.0.102:8084 | `argocd/argocd-repo-server-host` | VictoriaMetrics |
| 10.43.0.110:8000 | `kyverno/kyverno-admission-host` | VictoriaMetrics |
| 10.43.0.111:8000 | `kyverno/kyverno-reports-host` | VictoriaMetrics |
| 10.43.0.120:8080 | `kube-system/kube-state-metrics-host` | VictoriaMetrics |

Pick the next free address here and add a row. If the pods behind one have a NetworkPolicy, allow the hosts
(`argocd/extras/host-scrape-netpol.yaml`). The in-cluster Caddy uses these addresses too (Argo CD, edge-auth), never Service names: the front door must keep
working while kube-dns is down.

## Addresses outside the cluster

| Address | What | Set by |
|---|---|---|
| 192.168.86.10 | k3s API VIP (`k8s.nghodki.ai` on the LAN) | kube-vip, lease `kube-system/plndr-cp-lock` |
| 192.168.86.11 | edge VIP: `edge-dns-lan` :53, `edge-caddy-lan` :80/:443 | kube-vip (`kube-vip.io/loadbalancerIPs`), lease `plndr-svcs-lock` |
| 100.65.137.82, 100.124.175.23 | the Sparks' Tailscale IPs: `edge-dns-tailnet` :53, `edge-caddy-tailnet` :80/:443 | `externalIPs` (kube-proxy) |

Both VIPs are below the Nest's DHCP pool (`.20`–`.250`). LoadBalancer Services here set
`allocateLoadBalancerNodePorts: false` (no NodePorts on every node address).

## Host namespaces and capabilities (Kyverno allowlist)

| Pod | Namespace | Needs | Why |
|---|---|---|---|
| kube-vip (DaemonSet, Sparks) | kube-system (allowlisted) | **hostNetwork**, `NET_ADMIN`, `NET_RAW` (not privileged) | adds the VIPs to `wlP9s9` and sends gratuitous ARP |
| edge-dns | edge | `NET_BIND_SERVICE` (all else dropped) | the image's `/coredns` carries that file capability; without it exec fails |
| edge-caddy | edge | sysctl `net.ipv4.ip_unprivileged_port_start=0` (namespaced, "safe"), no capabilities | :80/:443 as a non-root user |

`edge` is excluded from Kyverno's webhooks (like kube-system and argocd) so the front door can restart while Kyverno
is down; background scans still report on it (decision 0007).
