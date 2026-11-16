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
- **SBOM:** BuildKit's SPDX SBOM and provenance per platform live in the image index, so the signature covers them;
  the arm64 SBOM is also attached as a signed cosign attestation (`spdxjson`) that a policy can require later.
- **Admission:** a Kyverno `ImageValidatingPolicy` (`verify-images`) for `ghcr.io/nikghodki/*` with that identity
  and issuer, `mutateDigest` (the tag in a manifest becomes the verified digest) and `verifyDigest`. Third-party
  images aren't signed by us; the registry allowlist and digest pinning cover them (runbooks/kyverno.md has the
  final scope per policy).

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
- Actions minutes: a cold build of both images and the signing steps run once per image change; see
  runbooks/build-sign.md for the measured times.
