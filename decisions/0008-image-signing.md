# 0008: Image signing: cosign keyless from GitHub Actions; Kyverno enforces it and the other P3.5 policies

- Date: 2026-11-15
- Status: decided (nikghodki)

## Context

Plan P3.5: "Kyverno (signed images, no privileged pods except an allowlist, limits, no `latest`); `build-sign.yml`
with cosign keyless. Acceptance: an unsigned image is rejected; a signed one runs." Decision 0006 put Kyverno in
Audit with a single replica and failurePolicy Ignore. The repo is private on GitHub Free (decision 0001): limited
Actions minutes, no free arm64 hosted runners for private repos, and the fleet is arm64 (Sparks, Jetson) plus one
amd64 node (Omarchy).

## Decision

- **Keyless signing (Sigstore) from `build-sign.yml` on `main`.** The workflow's GitHub OIDC token gets a short-lived
  Fulcio certificate whose subject is the workflow file at `refs/heads/main`; the signature is logged in Rekor. No
  private key to store, rotate or leak, and the identity says *which workflow on which branch* built the image, which
  is what admission should trust. The job is the only one with `packages: write` and `id-token: write`, and it only
  runs on `main` (push of an image's files, or a manual run); never on pull requests.
- **Images built:** `mlflow` and `ros-zenoh`, for `linux/amd64` and `linux/arm64` (amd64 is native and costs
  little; arm64 under QEMU on `ubuntu-24.04`). **The MuJoCo image is not built in CI**: about 12 GB of CUDA wheels,
  close to a hosted runner's free disk, a slow QEMU build and push, and a large share of the monthly minutes for an
  image that only runs as a job on the Sparks. It stays a local build until the self-hosted runner on dgx-2 (P4.8),
  where the same workflow can build and sign it with the same identity. The ROS/Zenoh image is the acceptance case.
- **SBOM:** BuildKit's SPDX SBOM (every file) and provenance per platform live in the image index, so the signature
  covers them; the arm64 SBOM at package level is also attached as a signed cosign attestation (`spdxjson`) that a
  policy can require later. Package level because Rekor refuses entries over about 32 MB and the ROS image's full
  SPDX is 33 MB (3.3 MB without the file list).
- **Admission:** a Kyverno `ImageValidatingPolicy` (`verify-images`) for `ghcr.io/nikghodki/*` with that identity
  and issuer, `mutateDigest` (the tag in the Pod becomes the verified digest) and `verifyDigest`. Pods only: a
  digest written into a Deployment would differ from Git and Argo CD's selfHeal would fight the webhook.
- **Third-party images:** not signed by us; covered by the registry allowlist and a new **`require-image-digest`**
  policy (Enforce). It skips `argocd`, `kyverno`, `cnpg-system` and `kube-system`, whose Helm charts / k3s render
  tags (pinned through the chart version); pinning those charts by digest would mean overriding every chart image
  for little gain. Every workload namespace from `cluster/apps` gets digests.
- **Enforce everything**, with `failurePolicy: Fail`, but the webhooks never see `kube-system`, `kyverno`, `argocd`
  (and `edge` until P3.3 is merged): a dead Kyverno can't stop the cluster's add-ons, Kyverno or Argo CD from
  restarting. **Two admission replicas**, one per Spark (hard topology spread, PDB 1), so one Spark's OOM doesn't
  stop admission; about 130 MiB more memory. `require-resource-limits` skips `kube-system`: k3s's coredns and
  local-path-provisioner come from k3s's packaged manifests (no HelmChartConfig; edits are overwritten on restart).
- **Packages public** for `mlflow` and `ros-zenoh` (nothing private inside), so neither Kyverno nor the nodes need a
  registry credential; an image with private code would get a read-only pull Secret instead.

## Alternatives considered

- **A cosign key pair** (key in SOPS, public key in the policy). Works offline, but a long-lived key to protect and
  rotate, and a signature says nothing about where it was made.
- **Notation / Notary v2.** Needs a CA or keys too; cosign keyless is what Kyverno and GHCR tooling do best.
- **Building on dgx-2 with a self-hosted runner now.** Native arm64 and no minute limit, but the runner (P4.8) isn't
  set up yet and a self-hosted runner on a private repo is a bigger trust decision; hosted runners for now.
- **Native arm64 hosted runners (`ubuntu-24.04-arm`).** Not free for private repos on the Free plan.

## Consequences

- Kyverno needs to reach the registry and Sigstore's TUF CDN to verify; a registry outage stops new pods that use
  `ghcr.io/nikghodki/*` images in enforced namespaces (not running ones).
- A signature from a branch, a fork or a laptop is refused; to ship an image it has to be merged.
- Actions minutes: about 4 billed minutes per build of both images (measured; runbooks/build-sign.md), only when an
  image's files change. Only GitHub-owned actions are allowed in this repo, so the workflow uses pinned binaries
  and images instead of the docker/sigstore actions.
- Break glass (a policy back to Audit, or removing Kyverno's webhooks) is in runbooks/kyverno.md and was tested.
