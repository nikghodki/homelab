---
title: Kyverno
description: "Admission policies in k3s: six policies in Enforce, what each checks and where it doesn't apply, the excluded namespaces, private-image pulls, break-glass, and the P3.5 acceptance results."
---

Kyverno 1.20.0 (chart 3.10.0) runs in its own namespace `kyverno` on the Sparks. **Since P3.5 (PR #65) every policy
Enforces** (`validationActions: [Deny]`, `failurePolicy: Fail`) in the namespaces its webhooks see; violations are
refused at admission and also show up in PolicyReports. Decisions 0006 (Audit phase, replaced) and 0008 (signing and
Enforce); runbooks/kyverno.md.

| | |
|---|---|
| Values | `cluster/platform/kyverno/values.yaml` |
| Admission controller | **2 replicas, one per Spark** (topology spread `DoNotSchedule` on hostname, PDB `minAvailable: 1`), so one Spark's OOM doesn't stop admission |
| Reports controller | 1 replica (hourly background scans, 1 worker, PolicyReports) |
| Off | background (generate/mutate-existing) and cleanup controllers, policy exceptions, the pre-delete webhook cleanup hook, `forceFailurePolicyIgnore` |
| Webhook scope | the webhooks' `namespaceSelector` leaves out **`kube-system`, `kyverno`, `argocd`** and **`edge`** (the front door, decision 0007). Those are never blocked, even with Kyverno dead; background scans still report on them |
| Policies | `policies/kyverno/*.yaml`, app `kyverno-policies`: five `ValidatingPolicy` (CEL) and one `ImageValidatingPolicy` |
| Metrics | admission 10.43.0.110:8000 (ClientIP affinity: the scrape sees one replica at a time), reports 10.43.0.111:8000 |
| Alerts | `KyvernoAdmissionDown` (critical), `KyvernoAdmissionDegraded`, `KyvernoRejectionsSpike`, `KyvernoWebhookErrors`, `KyvernoAdmissionSlow` ([Alert rules](../observability/alert-rules.md)) |
| Memory | admission 128Mi/384Mi per replica (52–65 MiB used), reports 64Mi/256Mi (46 MiB); Kyverno requests 320 Mi in total |

Why its own namespace: Kyverno skips its own namespace at admission, so putting it in `security` (as architecture §3.1
first said) would let the Fleet broker, proxy and Tetragon escape the policies.

## Policies

The `ValidatingPolicy` ones match Pods and, through autogen, Deployments, StatefulSets, DaemonSets, Jobs and CronJobs,
so a bad Deployment is refused before it makes pods.

| Policy | Checks | Not applied in (besides the webhook-excluded namespaces) |
|---|---|---|
| `verify-images` (ImageValidatingPolicy) | every `ghcr.io/nikghodki/*` image has a cosign keyless signature from `build-sign.yml` at `refs/heads/main` (issuer `https://token.actions.githubusercontent.com`); the tag is replaced by the verified digest (`mutateDigest`, `verifyDigest`). Pods only (a mutated Deployment would fight Argo CD's selfHeal), admission only, 20 s timeout | — |
| `disallow-latest-tag` | every image has a tag that isn't `latest`, or a digest | — |
| `restrict-registries` | image starts with an allowed prefix (below) | — |
| `require-image-digest` | every image **outside `ghcr.io/nikghodki`** is pinned by digest | `cnpg-system` (its chart renders tags; the chart version pins them) |
| `disallow-privileged` | no privileged container, no `hostNetwork`, `hostPID`, `hostIPC` | allowlist: `kube-system` (k3s add-ons, kube-vip), `kyverno`, `cnpg-system` |
| `require-resource-limits` | every container and init container has cpu and memory requests and limits | `kube-system` (k3s's `coredns` and `local-path-provisioner` come from packaged manifests that k3s rewrites on restart) |

**Allowed registries:** `ghcr.io/nikghodki/`, `docker.io/rancher/` (k3s), `quay.io/argoproj/`, the Argo CD redis image
(`ecr-public.aws.com` / `public.ecr.aws` `docker/library/redis`), `quay.io/viaductoss/ksops`, `reg.kyverno.io/kyverno/`,
`ghcr.io/kyverno/`, `ghcr.io/cloudnative-pg/`, and for P3.3 `ghcr.io/kube-vip/kube-vip`, `docker.io/library/caddy`,
`registry.k8s.io/kube-state-metrics/kube-state-metrics`. Names without a registry count as `docker.io/...`.

Everything else (`default`, `smoke`, `cnpg-system`, and every new namespace from `cluster/apps`) is enforced.

**Why `edge` stays out** (decision 0007): enforced, edge-caddy and edge-dns could only be recreated while a Kyverno
replica is up, and the front door must survive a dead Kyverno, like Argo CD. Its pods pass every policy (`kyverno apply`
on the live pods, 2026-11-15: 33 pass, 0 fail); check new `edge` manifests with `kyverno apply` before merging.

## Our own images and GHCR visibility

GHCR packages pushed from this private repo start **private**. Kyverno (to read signatures) and the nodes (to pull) can't
read them without a credential, so **every `ghcr.io/nikghodki` image is refused with `UNAUTHORIZED` until its package
is public**. Decision 0008 says to make `mlflow` and `ros-zenoh` public (nothing private inside); that is a one-time
click in the GitHub UI (Packages → the package → Package settings → Change visibility → Public) and was **not done yet**
at the time of writing: a user action. An image with private code would instead get a read-only pull Secret (a classic
PAT with `read:packages` as a SOPS `dockerconfigjson` in `kyverno` and in the workload's namespace).

## Before merging a workload

CI runs the Kyverno CLI on every PR (`.github/scripts/check-kubernetes.sh`): a pod that breaks every rule must fail
every `ValidatingPolicy`, then `cluster/` is checked. Check new manifests yourself too:
`kyverno apply policies/kyverno --resource <manifests>`. Name third-party images by digest; our own by tag.

## Findings

```bash
export KUBECONFIG=~/.kube/config
kubectl get validatingpolicies,imagevalidatingpolicies          # READY true
kubectl get policyreports -A
kubectl get events -A --field-selector reason=PolicyViolation
```

A refused request shows the policy's message in the `kubectl` or Argo CD error.

## Break-glass (tested 2026-11-15)

- **A. One policy to Audit, Kyverno up.** Remove `automated` from the `root` and `kyverno-policies` Applications (or
  selfHeal undoes you within seconds), then `kubectl patch validatingpolicy <name> --type merge -p '{"spec":{"validationActions":["Audit"]}}'`
  (or the `imagevalidatingpolicy`). Fix it in Git, then put `root`'s automated sync back; it restores everything.
- **B. Kyverno down or hung, pods refused** (`failed calling webhook ... kyverno-svc`). kube-system, kyverno and argocd
  keep working, so look first (`kubectl -n kyverno get pods`). To admit unchecked: stop selfHeal on `root` and `kyverno`,
  **scale the admission controller to 0 first** (on a clean shutdown it removes its own webhooks), then delete leftover
  webhooks with `kubectl delete validatingwebhookconfiguration,mutatingwebhookconfiguration -l webhook.kyverno.io/managed-by=kyverno`.
  Turning `root`'s automated sync back on restores 2 replicas and the webhooks in about 40 s.
- **C. Permanent:** a PR that sets the policy to `[Audit]` or adds an exemption.

Exact commands: runbooks/kyverno.md.

## Acceptance (P3.5, 2026-11-15)

In a scratch namespace, with `kubectl create --dry-run=server`: a compliant pod was admitted; an unsigned
`ghcr.io/nikghodki` image, a `:latest` image, a pod without limits, a privileged / `hostNetwork` pod, an image from
an unlisted registry and a Deployment with `:latest` were all **rejected**. The signed `ros-zenoh:kilted-1` was also
rejected, with `UNAUTHORIZED`, because the package is still private; after making it public it should be admitted with
the tag rewritten to the digest. Break-glass A and B were exercised and restored by Argo CD.

## Removing Kyverno

After deleting the app, delete its webhooks in the same step:
`kubectl delete validatingwebhookconfiguration,mutatingwebhookconfiguration -l webhook.kyverno.io/managed-by=kyverno`.
With failurePolicy Fail a leftover webhook with no Kyverno behind it **blocks** pod creation in enforced namespaces.
