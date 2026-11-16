# Kyverno (plan P3.5, Audit phase)

Admission policies for the cluster. **All policies are in Audit mode**: nothing is rejected yet; violations show up
in PolicyReports. Why Audit first, and why its own namespace: [decision 0006](../decisions/0006-gitops-platform.md).

| | |
|---|---|
| Version | Kyverno **v1.20.0**, Helm chart `kyverno` **3.10.0** (`cluster/bootstrap/apps/kyverno.yaml`); CI uses kyverno-cli v1.20.0 |
| Values | `cluster/platform/kyverno/values.yaml` |
| Runs | namespace **`kyverno`**, Sparks only, one replica each: **admission controller** and **reports controller** (background scans, PolicyReports). Background (generate/mutate-existing) and cleanup controllers are off |
| Webhooks | `forceFailurePolicyIgnore: true`: every Kyverno webhook has failurePolicy Ignore, so if Kyverno is down the API server admits pods unchecked instead of failing. Kyverno's config (`config.webhooks`, chart default) leaves `kube-system` out of admission; background scans still report on it |
| Policies | `policies/kyverno/*.yaml`, `ValidatingPolicy` (`policies.kyverno.io/v1`, CEL; the old `ClusterPolicy` type is deprecated in 1.20), app `kyverno-policies` |
| Metrics | admission `10.43.0.110:8000`, reports `10.43.0.111:8000` (VictoriaMetrics on dgx-2) |
| Alert | `KyvernoAdmissionDown` (5 min), `hosts/stacks/observe/vmalert/rules/gitops.yml` |

## Policies

All match Pods; Kyverno also reports on their Deployments, ReplicaSets, StatefulSets and Jobs (autogen).

| Policy | Checks |
|---|---|
| `require-resource-limits` | every container and init container has cpu and memory **requests and limits** |
| `disallow-latest-tag` | every image has a tag that isn't `latest`, or a digest |
| `disallow-privileged` | no `privileged` container, no `hostNetwork`/`hostPID`/`hostIPC`. **Allowlist** (namespaces skipped): `kube-system`, `kyverno`, `cnpg-system`. Argo CD doesn't need it |
| `restrict-registries` | image starts with an allowed prefix: `ghcr.io/nikghodki/`, `docker.io/rancher/` (k3s), `quay.io/argoproj/`, the Argo CD redis image (`ecr-public.aws.com`/`public.ecr.aws` `docker/library/redis`), `quay.io/viaductoss/ksops`, `reg.kyverno.io/kyverno/`, `ghcr.io/kyverno/`, `ghcr.io/cloudnative-pg/`. Names without a registry count as `docker.io/...` |

Add a registry or an allowlisted namespace by editing the policy (a reviewed PR). CI runs the Kyverno CLI on every
PR (`.github/scripts/check-kubernetes.sh`): a pod that breaks every rule must fail every policy (this also catches a policy that
doesn't parse, which the CLI otherwise skips silently), then `cluster/` is checked.

**Signed images (cosign keyless)** are the Enforce step of P3.5 and need the `build-sign.yml` workflow, which doesn't
exist yet. Follow-up: add `build-sign.yml`, then an `ImageValidatingPolicy` for `ghcr.io/nikghodki/*` (issuer
`https://token.actions.githubusercontent.com`, subject `https://github.com/nikghodki/homelab/.github/workflows/build-sign.yml@refs/heads/main`),
Audit first like the others.

## Findings

```bash
export KUBECONFIG=~/.kube/config
kubectl get validatingpolicies                         # READY true
kubectl get policyreports -A                           # one per resource: PASS / FAIL columns
kubectl get policyreports -A -o json | jq -r '.items[] | select(.scope.kind=="Pod") | .scope as $s
  | .results[] | select(.result!="pass") | "\($s.namespace)/\($s.name)  \(.policy): \(.message)"'
```

Background scans run every hour (and on every change); admission results arrive as pods are created.

First results, 2026-11-15 (11 pods: argocd, kyverno, cnpg-system, kube-system):

| Policy | Pass | Fail |
|---|---|---|
| `require-resource-limits` | 9 | 2 |
| `disallow-latest-tag` | 11 | 0 |
| `disallow-privileged` | 4 | 0 (kube-system, kyverno, cnpg-system skipped) |
| `restrict-registries` | 11 | 0 |

The two failures are k3s's own add-ons in `kube-system`: `coredns` (memory limit but no cpu limit) and
`local-path-provisioner` (no requests or limits). They are k3s-managed; leave them, or set them through k3s's
manifests (`/var/lib/rancher/k3s/server/manifests`) before Enforce, or exclude `kube-system` from that policy.

## Audit → Enforce

Per policy, when its findings are clean (or the exceptions are decided):

1. `kubectl get policyreports -A` shows no `fail` for it, for at least a week of normal changes.
2. In `policies/kyverno/<policy>.yaml` set `validationActions: [Deny]` (keep `Audit` out; `Warn` first for a few days
   is a gentle middle step: `[Warn, Audit]`).
3. Before the **first** Enforce policy, in `cluster/platform/kyverno/values.yaml`: remove
   `forceFailurePolicyIgnore` (so a policy can actually block when Kyverno is up), and consider 2 admission
   replicas (one per Spark) so a GPU OOM on one Spark doesn't stop admission. With failurePolicy Fail and a single
   replica, a dead Kyverno blocks pod creation in every matched namespace.
4. PR; CI runs the CLI; merge. Check a known-bad pod is refused:
   `kubectl run t --image=nginx --dry-run=server -n default` must fail.

Order suggested: `disallow-latest-tag`, `restrict-registries`, `disallow-privileged`, `require-resource-limits`
(after the k3s add-ons are dealt with), then signed images.

## Removing Kyverno

The pre-delete webhook cleanup hook is disabled. After deleting the app, remove leftovers:
`kubectl delete validatingwebhookconfiguration,mutatingwebhookconfiguration -l webhook.kyverno.io/managed-by=kyverno`.
With failurePolicy Ignore a leftover webhook only costs a timeout per request.

## Resources (2026-11-15)

| Pod | Request / limit | anon | incl. cache | peak |
|---|---|---|---|---|
| admission controller | 128Mi / 384Mi | 64 MiB | 65 MiB | 77 MiB |
| reports controller | 64Mi / 256Mi | 43 MiB | 44 MiB | 62 MiB |

The CRD-migration Job (`kyverno-migrate-resources`, a post-upgrade hook = Argo CD PostSync) runs briefly when the
app syncs (limit 256Mi).
