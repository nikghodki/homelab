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
| Webhooks | `failurePolicy: Fail` (each policy sets it; `forceFailurePolicyIgnore` is off). The webhooks' `namespaceSelector` (`config.webhooks`) leaves out **`kube-system`, `kyverno`, `argocd`** and, until P3.3 is merged, **`edge`**: those are never blocked, even with Kyverno dead. Background scans still report on them |
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
| `require-image-digest` | Enforce | every image **outside `ghcr.io/nikghodki`** is pinned by digest (`image@sha256:`) | also `cnpg-system` (and the platform namespaces): their Helm charts render tags; the chart version pins them, and the registry and `latest` policies still apply |
| `disallow-privileged` | Enforce | no `privileged` container, no `hostNetwork`/`hostPID`/`hostIPC` | **allowlist**: `kube-system` (k3s add-ons, kube-vip: hostNetwork + NET_ADMIN/NET_RAW), `kyverno`, `cnpg-system` |
| `require-resource-limits` | Enforce | every container and init container has cpu and memory **requests and limits** | **`kube-system`**: k3s's `coredns` (no cpu limit) and `local-path-provisioner` (none) come from k3s's packaged manifests, not a HelmChart, so there's no HelmChartConfig to set them and edits under `/var/lib/rancher/k3s/server/manifests` are overwritten when k3s restarts |

"Webhook-excluded namespaces" = `kube-system`, `kyverno`, `argocd`, `edge` (until P3.3 merges). Everything else
(`default`, `smoke`, `cnpg-system`, and every new namespace from `cluster/apps`) is enforced.

**Allowed registries** (`restrict-registries`): `ghcr.io/nikghodki/`, `docker.io/rancher/` (k3s), `quay.io/argoproj/`,
the Argo CD redis image (`ecr-public.aws.com`/`public.ecr.aws` `docker/library/redis`), `quay.io/viaductoss/ksops`,
`reg.kyverno.io/kyverno/`, `ghcr.io/kyverno/`, `ghcr.io/cloudnative-pg/`, and for P3.3 `ghcr.io/kube-vip/kube-vip`,
`docker.io/library/caddy`, `registry.k8s.io/kube-state-metrics/kube-state-metrics`. Names without a registry count
as `docker.io/...`.

Add a registry, a namespace exemption or an allowlist entry by editing the policy (a reviewed PR). CI runs the
Kyverno CLI on every PR (`.github/scripts/check-kubernetes.sh`): a pod that breaks every rule must fail every
`ValidatingPolicy` (this also catches a policy that doesn't parse, which the CLI otherwise skips silently), then
`cluster/` is checked. Before merging a new workload, check it the same way against the live policies:
`kyverno apply policies/kyverno --resource <manifests>`.

**TODO (P3.3):** when `p3.3-edge-in-cluster` is merged, take `edge` out of `config.webhooks` in
`cluster/platform/kyverno/values.yaml`. Its pods (edge-caddy, edge-dns) passed every policy on 2026-11-15
(`kyverno apply` on the live objects) once the three P3.3 registries above are allowed; re-check them, then merge.
With `edge` enforced, edge-caddy and edge-dns can only be recreated while a Kyverno replica is up.

## Private images

GHCR packages pushed from this private repo are **private**. Kyverno (to read signatures) and the nodes (to pull)
need either the package set to public, or a pull credential:

- **Public** (chosen for `mlflow` and `ros-zenoh`, which contain nothing private): github.com → Packages →
  `<name>` → Package settings → Change visibility → Public. Nothing else to configure.
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

**B. Kyverno down and pods refused** (both admission replicas gone; `KyvernoAdmissionDown`). kube-system, kyverno
and argocd are never blocked, so Kyverno and Argo CD can still restart. If it doesn't come back:

```bash
kubectl -n kyverno get pods; kubectl -n kyverno describe deploy kyverno-admission-controller
# Remove the resource webhooks: the API server stops calling Kyverno, everything is admitted unchecked.
kubectl delete validatingwebhookconfiguration,mutatingwebhookconfiguration -l webhook.kyverno.io/managed-by=kyverno
```

Kyverno recreates its webhooks when an admission replica is ready again. The policy webhooks
(`kyverno-policy-validating-webhook-cfg`) also fail closed, which only matters for creating or changing policies.

**C. Permanent:** a PR that sets the policy to `validationActions: [Audit]` (or adds the exemption). Argo CD applies
it within about 3 minutes.

## Acceptance (P3.5, 2026-11-15)

In a scratch namespace (deleted afterwards). Results are in the PR that switched to Enforce.

## Removing Kyverno

The pre-delete webhook cleanup hook is disabled. After deleting the app, remove leftovers:
`kubectl delete validatingwebhookconfiguration,mutatingwebhookconfiguration -l webhook.kyverno.io/managed-by=kyverno`.
With failurePolicy Fail, a leftover webhook with no Kyverno behind it **blocks** pod creation in enforced
namespaces: delete the webhooks in the same step.

## Resources

| Pod | Request / limit | anon | incl. cache | peak |
|---|---|---|---|---|
| admission controller (Audit, 1 replica, 2026-11-15) | 128Mi / 384Mi | 64 MiB | 65 MiB | 77 MiB |
| reports controller | 64Mi / 256Mi | 43 MiB | 44 MiB | 62 MiB |

The CRD-migration Job (`kyverno-migrate-resources`, a post-upgrade hook = Argo CD PostSync) runs briefly when the
app syncs (limit 256Mi).
