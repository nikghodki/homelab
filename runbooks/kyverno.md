# Kyverno (plan P3.5, Enforce)

Admission policies for the cluster. **All policies Enforce** (`validationActions: [Deny]`, `failurePolicy: Fail`)
in the namespaces Kyverno's webhooks see; violations are refused at admission and also show up in PolicyReports
(background scans). Why: [decision 0006](../decisions/0006-gitops-platform.md) (Audit phase),
[decision 0008](../decisions/0008-image-signing.md) (signing and Enforce). Image signing: [build-sign.md](build-sign.md).

| | |
|---|---|
| Version | Kyverno **v1.20.0**, Helm chart `kyverno` **3.10.0** (`cluster/bootstrap/apps/kyverno.yaml`); CI uses kyverno-cli v1.20.0 |
| Values | `cluster/platform/kyverno/values.yaml` |
| Runs | namespace **`kyverno`**, Sparks only. **Admission controller: 2 replicas, one per Spark** (topology spread `DoNotSchedule` on hostname, PDB `minAvailable: 1`). Reports controller: 1 replica (background scans, PolicyReports). Background and cleanup controllers off |
| Webhooks | `failurePolicy: Fail` (each policy sets it; `forceFailurePolicyIgnore` is off). The webhooks' `namespaceSelector` (`config.webhooks`) leaves out **`kube-system`, `kyverno`, `argocd`** and **`edge`** (the front door, decision 0007): those are never blocked, even with Kyverno dead. Background scans still report on them |
| Policies | `policies/kyverno/*.yaml`, app `kyverno-policies`: five `ValidatingPolicy` (CEL) and one `ImageValidatingPolicy` |
| Metrics | admission `10.43.0.110:8000` (ClientIP affinity: one replica at a time), reports `10.43.0.111:8000` (VictoriaMetrics on dgx-2) |
| Alerts | `hosts/stacks/observe/vmalert/rules/gitops.yml`: `KyvernoAdmissionDown` (critical, 5 min), `KyvernoAdmissionDegraded` (< 2 replicas, needs kube-state-metrics), `KyvernoRejectionsSpike` (> 5 refusals in 15 min), `KyvernoWebhookErrors` (5xx), `KyvernoAdmissionSlow` (p99 > 8 s) |

## Policies and scope

All match Pods; the `ValidatingPolicy` ones also check Deployments, StatefulSets, DaemonSets, Jobs and CronJobs
(autogen), so a bad Deployment is refused before it makes pods.

| Policy | Mode | Checks | Not applied in |
|---|---|---|---|
| `verify-images` (ImageValidatingPolicy) | Enforce | every `ghcr.io/nikghodki/*` image has a cosign keyless signature from `build-sign.yml` at `refs/heads/main` (issuer `https://token.actions.githubusercontent.com`); the tag is **replaced by the verified digest** (`mutateDigest`, `verifyDigest`). Pods only (no autogen: a mutated Deployment would fight Argo CD's selfHeal); admission only | webhook-excluded namespaces |
| `disallow-latest-tag` | Enforce | every image has a tag that isn't `latest`, or a digest | webhook-excluded namespaces |
| `restrict-registries` | Enforce | image starts with an allowed prefix (list below) | webhook-excluded namespaces |
| `restrict-ephemeral-containers` | Enforce, admission only | `kubectl debug` containers: allowed registry (the same list), digest, not `latest`, not privileged | webhook-excluded namespaces, `cnpg-system` |
| `require-image-digest` | Enforce | every image **outside `ghcr.io/nikghodki`** is pinned by digest (`image@sha256:`) | also `cnpg-system` (and the platform namespaces): their Helm charts render tags; the chart version pins them, and the registry and `latest` policies still apply |
| `disallow-privileged` | Enforce | no `privileged` container, no `hostNetwork`/`hostPID`/`hostIPC` | **allowlist**: `kube-system` (k3s add-ons, kube-vip: hostNetwork + NET_ADMIN/NET_RAW), `kyverno`, `cnpg-system` |
| `require-resource-limits` | Enforce | every container and init container has cpu and memory **requests and limits** | **`kube-system`**: k3s's `coredns` (no cpu limit) and `local-path-provisioner` (none) come from k3s's packaged manifests, not a HelmChart, so there's no HelmChartConfig to set them and edits under `/var/lib/rancher/k3s/server/manifests` are overwritten when k3s restarts |

**Ephemeral containers** (`kubectl debug`) go through the `pods/ephemeralcontainers` subresource. Since 2026-11-16
(code review #10; before, a debug container from any registry, `:latest` or privileged was admitted: tested) the
separate policy **`restrict-ephemeral-containers`** (admission only) applies the registry, digest, tag and privilege
rules to them; its registry list must equal `restrict-registries`' (CI checks). The pod policies don't match the
subresource themselves: a background scan can't list it, the policy then reports "not ready for reporting" and Argo CD
shows `kyverno-policies` Degraded. `require-resource-limits` doesn't apply (ephemeral containers can't have resources).
Tested live: a debug container from `evil.example.com` with `:latest` is refused, one with an allowed image by digest
is admitted.

"Webhook-excluded namespaces" = `kube-system`, `kyverno`, `argocd`, `edge`. Everything else
(`default`, `smoke`, `cnpg-system`, and every new namespace from `cluster/apps`) is enforced.

**Allowed registries** (`restrict-registries`): `ghcr.io/nikghodki/`, `docker.io/rancher/` (k3s), `quay.io/argoproj/`,
the Argo CD redis image (`ecr-public.aws.com`/`public.ecr.aws` `docker/library/redis`), `quay.io/viaductoss/ksops`,
`reg.kyverno.io/kyverno/`, `ghcr.io/kyverno/`, `ghcr.io/cloudnative-pg/`, and for P3.3 `ghcr.io/kube-vip/kube-vip`,
`docker.io/library/caddy`, `registry.k8s.io/kube-state-metrics/kube-state-metrics`, `quay.io/oauth2-proxy/oauth2-proxy` (edge-auth, decision 0011), and for the ops agent (decision 0013) the read-only MCP servers `docker.io/grafana/mcp-grafana`, `quay.io/containers/kubernetes_mcp_server` and `ghcr.io/argoproj-labs/mcp-for-argocd` (exact image names, digests required). Names without a registry count
as `docker.io/...`.

Add a registry, a namespace exemption or an allowlist entry by editing the policy (a reviewed PR). CI runs the
Kyverno CLI on every PR (`.github/scripts/check-kubernetes.sh`): a pod that breaks every rule must fail every
`ValidatingPolicy` (this also catches a policy that doesn't parse, which the CLI otherwise skips silently), then
`cluster/` is checked. Before merging a new workload, check it the same way against the live policies:
`kyverno apply policies/kyverno --resource <manifests>`.

**`edge` stays out of the webhooks (P3.3, decision 0007).** With `edge` enforced, edge-caddy and edge-dns could only
be recreated while a Kyverno replica is up, and the front door must survive a dead Kyverno, like Argo CD. Its pods
pass every policy (`kyverno apply` on the live pods, 2026-11-15: 33 pass, 0 fail), and background scans keep
reporting on them; check new `edge` manifests with `kyverno apply` before merging.

## Private images

GHCR packages pushed from this private repo are **private**. Kyverno (to read signatures) and the nodes (to pull)
need either the package set to public, or a pull credential:

- **Public** (decision 0008, for `mlflow` and `ros-zenoh`, which contain nothing private): github.com → Packages →
  `<name>` → Package settings → Change visibility → Public (UI only; the API can't change it). Nothing else to
  configure. **Not done yet**: until then every `ghcr.io/nikghodki` image is refused with `UNAUTHORIZED`.
- **Private** (for an image with private code): a classic PAT with only `read:packages`, as a SOPS-encrypted
  `kubernetes.io/dockerconfigjson` Secret in `kyverno` (add `credentials: {secrets: [ghcr-pull]}` to
  `verify-images`) and in the workload's namespace (`imagePullSecrets`).

## Findings

```bash
export KUBECONFIG=~/.kube/config
kubectl get validatingpolicies,imagevalidatingpolicies   # READY true
kubectl get policyreports -A                             # one per resource: PASS / FAIL columns
kubectl get policyreports -A -o json | jq -r '.items[] | select(.scope.kind=="Pod") | .scope as $s
  | .results[] | select(.result!="pass") | "\($s.namespace)/\($s.name)  \(.policy): \(.message)"'
kubectl get events -A --field-selector reason=PolicyViolation
```

Background scans run every hour (and on every change). A refused request shows the policy's message in the
`kubectl` / Argo CD error.

## Break glass

Use when a policy blocks something it shouldn't and a PR can't wait (or Kyverno itself is down).

**A. One policy back to Audit, Kyverno up** (tested 2026-11-15, see below). Argo CD's selfHeal would undo a manual
change within seconds, so stop it first:

```bash
export KUBECONFIG=~/.kube/config
# 1. Stop selfHeal (root re-applies kyverno-policies' Application; kyverno-policies re-applies the policy).
kubectl -n argocd patch application root             --type json -p '[{"op":"remove","path":"/spec/syncPolicy/automated"}]'
kubectl -n argocd patch application kyverno-policies --type json -p '[{"op":"remove","path":"/spec/syncPolicy/automated"}]'
# 2. The policy to Audit (or delete it: kubectl delete validatingpolicy <name>).
kubectl patch validatingpolicy disallow-latest-tag --type merge -p '{"spec":{"validationActions":["Audit"]}}'
# ImageValidatingPolicy: kubectl patch imagevalidatingpolicy verify-images --type merge -p '{"spec":{"validationActions":["Audit"]}}'
# 3. Fix it properly in Git (a PR), then hand back to Argo CD: root restores kyverno-policies' syncPolicy, which
#    re-applies every policy as in Git.
kubectl -n argocd patch application root --type merge -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
```

**B. Kyverno down or hung, pods refused** (`KyvernoAdmissionDown`, errors like `failed calling webhook ... kyverno-svc`).
kube-system, kyverno and argocd are never blocked, so Kyverno and Argo CD can still restart; look first:
`kubectl -n kyverno get pods; kubectl -n kyverno describe deploy kyverno-admission-controller`. To admit unchecked
until it's fixed (tested 2026-11-15):

```bash
# 1. Stop selfHeal (else the kyverno app scales it straight back up).
kubectl -n argocd patch application root    --type json -p '[{"op":"remove","path":"/spec/syncPolicy/automated"}]'
kubectl -n argocd patch application kyverno --type json -p '[{"op":"remove","path":"/spec/syncPolicy/automated"}]'
# 2. Stop the admission controller. On a clean shutdown Kyverno removes its own webhooks.
kubectl -n kyverno scale deploy kyverno-admission-controller --replicas=0
# 3. Webhooks left over (pods that crashed can't clean up): delete them. A *running* Kyverno recreates them at once,
#    which is why step 2 comes first.
kubectl delete validatingwebhookconfiguration,mutatingwebhookconfiguration -l webhook.kyverno.io/managed-by=kyverno
# 4. When fixed: root's automated sync back on; root restores the kyverno app, which restores 2 replicas; Kyverno
#    recreates the webhooks (about 40 s).
kubectl -n argocd patch application root --type merge -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
``` The policy webhooks
(`kyverno-policy-validating-webhook-cfg`) also fail closed, which only matters for creating or changing policies.

**C. Permanent:** a PR that sets the policy to `validationActions: [Audit]` (or adds the exemption). Argo CD applies
it within about 3 minutes.

## Acceptance (P3.5, 2026-11-15)

In a scratch namespace `p35-scratch` (deleted afterwards), right after the Enforce merge (#65). Pods with cpu/memory
requests and limits and the pinned `docker.io/rancher/mirrored-pause:3.6@sha256:74c4…a893` unless the test changes
that; rejections checked with `kubectl create --dry-run=server` (goes through every admission webhook).

| Test | Result |
|---|---|
| control: compliant pod | **admitted and Running** (dgx-1) |
| (a) unsigned `ghcr.io/nikghodki/mlflow:buildcache` | **rejected** by `verify-images`. While the packages are private the reason is `UNAUTHORIZED` from GHCR (Kyverno can't read the image), not the missing signature; re-run after making them public (below) |
| (b) signed `ghcr.io/nikghodki/ros-zenoh:kilted-1` | **pending: rejected with `UNAUTHORIZED`** while the package is private. After it is made public, expect admitted with the image rewritten to `…:kilted-1@sha256:…` |
| (c) `quay.io/argoproj/argocd:latest` | **rejected** (`require-image-digest`; with that one in Audit, `disallow-latest-tag`: "images without a tag, or tagged latest") |
| (d) no requests/limits | **rejected** (`require-resource-limits`: "containers without cpu/memory requests and limits: c") |
| (e) `privileged: true` / `hostNetwork: true` | **rejected** (`disallow-privileged`) |
| extra: `docker.io/library/busybox@sha256:…` | **rejected** (`restrict-registries`) |
| extra: Deployment with `:latest` | **rejected** before any pod (`disallow-latest-tag`, autogen) |
| (f) break glass A | `root` and `kyverno-policies` selfHeal off; `require-image-digest` → Audit: (c) still refused by `disallow-latest-tag`; `disallow-latest-tag` → Audit: **(c) admitted**; still Audit 30 s later (no selfHeal). Root's `automated` back on: both policies back to **Deny 11 s later**, (c) refused again |
| (f) fail closed + break glass B | `kyverno-svc` pointed at no endpoints (a hung Kyverno): a compliant pod in `p35-scratch` **refused** ("no endpoints available for service kyverno-svc"); the same pod in `argocd`, `kube-system` and `kyverno` **admitted**. Admission scaled to 0: Kyverno removed its webhooks on shutdown (0 left), compliant pod **admitted**. Root's `automated` back on: Service and 2 replicas restored, webhooks recreated, policies enforcing again in about 40 s |

Re-run (a) and (b) once the packages are public:

```bash
NS=p35-scratch; kubectl create ns $NS
for img in ghcr.io/nikghodki/mlflow:buildcache ghcr.io/nikghodki/ros-zenoh:kilted-1; do
cat <<P | kubectl create --dry-run=server -o jsonpath='{.spec.containers[0].image}{"\n"}' -f -
apiVersion: v1
kind: Pod
metadata: {name: t, namespace: $NS}
spec:
  containers:
    - {name: c, image: "$img", resources: {requests: {cpu: 10m, memory: 16Mi}, limits: {cpu: 50m, memory: 32Mi}}}
P
done   # expect: buildcache refused (no signature); kilted-1 printed with @sha256:...
kubectl delete ns $NS
```

## Removing Kyverno

The pre-delete webhook cleanup hook is disabled. After deleting the app, remove leftovers:
`kubectl delete validatingwebhookconfiguration,mutatingwebhookconfiguration -l webhook.kyverno.io/managed-by=kyverno`.
With failurePolicy Fail, a leftover webhook with no Kyverno behind it **blocks** pod creation in enforced
namespaces: delete the webhooks in the same step.

## Resources

| Pod | Request / limit | anon | incl. cache | peak |
|---|---|---|---|---|
| admission controller (Audit, 1 replica, 2026-11-15) | 128Mi / 384Mi | 64 MiB | 65 MiB | 77 MiB |
| admission controller, Enforce, dgx-1 (after the tests) | 128Mi / 384Mi | 52 MiB | 54 MiB | 57 MiB |
| admission controller, Enforce, dgx-2 (after the tests) | 128Mi / 384Mi | 65 MiB | 66 MiB | 72 MiB |
| reports controller | 64Mi / 256Mi | 46 MiB | 47 MiB | 65 MiB |

The second replica adds 128 Mi of requests (384 Mi limit); Kyverno in total now requests 320 Mi.

The CRD-migration Job (`kyverno-migrate-resources`, a post-upgrade hook = Argo CD PostSync) runs briefly when the
app syncs (limit 256Mi).
