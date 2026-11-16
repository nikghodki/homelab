# 0006: GitOps platform: Argo CD (Helm, self-managed), KSOPS, Kyverno in Audit, CNPG operator, single replicas

- Date: 2026-11-15
- Status: decided (nikghodki)

## Context

Plan P3.4 (Argo CD pulls the repo with a read-only deploy key; SOPS decryption in the cluster) and the first half of
P3.5 (Kyverno), on the k3s cluster from P3.2 (decision 0005). The Sparks are close to their memory limits from model
work (two GPU/unified-memory OOMs took them down on 2026-11-15), the Jetson has about 3 GB free and is tainted, so
the whole platform has to be small: budget about 2.5 GiB.

## Decision

- **Argo CD 3.6.1 from the official Helm chart (`argo-cd` 10.18.0), self-managed.** Installed once with `helm
  install` from dgx-1 using the same values file the `argocd` Application uses, then handed to Git through an
  app-of-apps (`cluster/bootstrap/apps/root.yaml`); Helm's release record is deleted afterwards. The chart over the
  upstream manifests because one values file covers resources, node selectors, KSOPS and OIDC without kustomize
  patches. App of apps over ApplicationSets: one less controller (about 50 MiB), and a dozen apps don't need
  generators. One replica of each component; Dex, notifications, ApplicationSet controller and commit server off.
- **Repo access:** an ed25519 deploy key, read-only, title `argocd-homelab`; private half in
  `secrets/argocd.enc.yaml`, loaded into the cluster by hand at bootstrap (the repo can't hold the credential
  needed to read itself). GitHub never connects in (D15): Argo CD polls every 2 minutes.
- **UI and metrics through fixed ClusterIPs**, not NodePorts: edge-caddy on dgx-1 and VictoriaMetrics on dgx-2 run
  in Docker on cluster nodes, and kube-proxy routes ClusterIPs for host traffic, so `argocd.nghodki.ai` →
  `10.43.0.100` and the scrape targets need nothing published on the LAN or Tailscale. NodePorts would listen on
  every node address, and k3s can only restrict that cluster-wide (`nodeport-addresses`, a k3s restart). The
  static band of the service CIDR keeps the IPs stable (cluster/README.md). The server runs in insecure mode;
  Caddy terminates TLS. P3.3 (Caddy in the cluster) replaces the Caddy path.
- **Sign-in:** Argo CD's own OIDC with Pocket ID (client `argocd`, PKCE S256, which Argo CD 3.6 sends in its
  server-side flow), RBAC `admins` → `role:admin`, no default role; built-in admin disabled, with a tested
  break-glass (runbooks/argocd.md). Pods resolve `*.nghodki.ai` through a CoreDNS zone that forwards to edge-dnsmasq
  and answers AAAA with an empty NOERROR (edge-dnsmasq's AAAA NXDOMAIN breaks Go resolvers).
- **SOPS: KSOPS** (v4.5.1) in the repo-server, not sops-secrets-operator. KSOPS is a kustomize exec plugin copied
  in by an init container: no extra controller, no CRD, no memory, and the encrypted files stay ordinary Secret
  manifests (`cluster/**/*.enc.yaml`, only `data`/`stringData` encrypted) that `sops` edits like `secrets/`. The
  operator would add a pod (~50 MiB), a CRD wrapper format and its own copy of the key. Both are maintained (KSOPS
  4.5.1, April 2026; the operator 0.22.3, November 2026); KSOPS is the simpler fit for Argo CD.
- **The fleet age key goes into the cluster** as the Secret `argocd/sops-age`, created from the file with
  `kubectl create secret --from-file`, mounted only into the repo-server. This changes the "key stays offline"
  part of D16: the key is now also on the cluster (etcd, encrypted at rest by k3s; readable by cluster admins). A
  second, cluster-only age key would limit what a cluster compromise exposes, but every SOPS file in `cluster/`
  would then need both recipients and a separate rotation. Revisit when workloads with their own secrets move in
  (P3.7): add a cluster recipient for `^cluster/` in `.sops.yaml` and drop the fleet key from the cluster.
- **Kyverno 1.20.0 (chart 3.10.0) in its own `kyverno` namespace, policies in Audit.** Not in `security`
  (architecture §3.1 listed it there): Kyverno skips its own namespace at admission, so the Fleet broker, proxy and
  Tetragon would escape the policies. Admission and reports controllers only; background and cleanup controllers
  off (no generate/cleanup policies). `ValidatingPolicy` (CEL), since `ClusterPolicy` is deprecated in 1.20. Audit
  first so the existing pods are reported, not broken; `forceFailurePolicyIgnore` so a single Kyverno replica on a
  Spark that can OOM never blocks the API. Signed-image verification waits for `build-sign.yml` (P3.5 Enforce).
- **CloudNativePG operator 1.30.1 (chart 0.29.1)** in `cnpg-system`, operator only, so P3.7 can add Postgres
  clusters in `data` from Git.
- **Single replicas** everywhere for now; HA (2 replicas, one per Spark) when the Sparks have memory to spare and
  before Kyverno enforces. Everything is pinned to the Sparks (`nghodki.ai/role=gpu`); nothing runs on the Jetson.

## Memory budget (measured 2026-11-15, cgroup memory.current)

| Component | Requests | Limits | Used (anon) | Used (incl. page cache) |
|---|---|---|---|---|
| Argo CD (controller, repo-server, server, redis) | 592 Mi | 1632 Mi | 491 MiB | 808 MiB |
| Kyverno (admission, reports) | 192 Mi | 640 Mi | 107 MiB | 109 MiB |
| CNPG operator | 64 Mi | 256 Mi | 22 MiB | 23 MiB |
| **Total** | **848 Mi** | **2528 Mi (2.47 GiB)** | **620 MiB** | **940 MiB** |

Within the ~2.5 GiB budget even at the limits. The application controller is the big one (it caches the cluster's
objects); it was OOM-killed once at 512 Mi during the first sync, so it has 768 Mi and `GOMEMLIMIT=600MiB`.

## Alternatives considered

- **Flux.** Lighter, but the plan, the architecture and the single-pane-of-glass design name Argo CD (UI, app
  health, OIDC); Flux would need a separate UI.
- **NodePort / hostPort for the UI and metrics.** Exposes plain HTTP on every node interface (above).
- **sops-secrets-operator; Sealed Secrets; External Secrets + a vault.** An extra controller each, and Sealed
  Secrets or a vault would replace SOPS (D16) rather than use it.
- **Kyverno in Enforce from the start.** Would have blocked k3s's own add-ons (no limits) and gives one replica the
  power to stop all pod creation during a Spark OOM.

## Consequences

- A merge to `cluster/` (or `policies/kyverno`) deploys within about 2 minutes, no manual step (P3.4 acceptance;
  measured 89 s for a label change).
- Two things in the cluster are not from Git: `argocd/sops-age` and `argocd/repo-homelab` (runbooks/argocd.md).
- The OIDC client secret exists twice (`secrets/console.enc.yaml` and `cluster/platform/argocd/extras/oidc.enc.yaml`);
  rotate both together.
- Next: P3.3 (kube-vip, DNS and Caddy in the cluster; the fixed-ClusterIP Caddy path goes away), P3.5 Enforce
  (build-sign.yml, signed-image policy, 2 Kyverno replicas, failurePolicy Fail), P3.7 (workloads into `cluster/apps`).
