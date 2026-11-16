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
│   └── smoke.yaml         SOPS canary (apps/_smoke)
├── platform/<component>/  values.yaml for the Helm chart and extras/ (kustomize: Services, NetworkPolicies, SOPS secrets)
│   ├── argocd/            Argo CD 3.6 + KSOPS in the repo-server
│   ├── kyverno/           Kyverno 1.20, admission + reports controllers
│   ├── cnpg-operator/     CloudNativePG 1.30 operator, no clusters yet
│   └── cluster-dns/       CoreDNS zone for *.nghodki.ai (forwards to edge-dnsmasq on dgx-1)
└── apps/                  workloads, one folder per app (README.md); `_smoke` is the SOPS canary
```

Kyverno's policies are in [`policies/kyverno`](../policies/kyverno) (app `kyverno-policies`).

## Rules

- **Pin everything.** Helm charts by version in the Application, images by digest when a manifest here names an
  image. No `latest`.
- **Requests and limits on every container**, one replica for now, and a `nodeSelector` on
  `nghodki.ai/role: gpu` (Sparks) or `agent-node` (Omarchy). Nothing goes on the Jetson unless it is meant to
  (it is tainted). Kyverno audits limits, tags, registries and privileged pods (runbooks/kyverno.md).
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
| 10.43.0.10:53 | kube-dns (k3s) | pods |
| 10.43.0.100:80, :8083 | `argocd/argocd-server-host` | edge-caddy (`argocd.nghodki.ai`), VictoriaMetrics |
| 10.43.0.101:8082 | `argocd/argocd-controller-host` | VictoriaMetrics |
| 10.43.0.102:8084 | `argocd/argocd-repo-server-host` | VictoriaMetrics |
| 10.43.0.110:8000 | `kyverno/kyverno-admission-host` | VictoriaMetrics |
| 10.43.0.111:8000 | `kyverno/kyverno-reports-host` | VictoriaMetrics |

Pick the next free address here and add a row. If the pods behind one have a NetworkPolicy, allow the hosts
(`argocd/extras/host-scrape-netpol.yaml`). P3.3 (kube-vip, Caddy in the cluster) replaces the edge-caddy path.
