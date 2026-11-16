---
title: Image signing (build-sign.yml)
description: How the fleet's own images are built, pushed to GHCR, signed with cosign keyless and given an SBOM, and how to verify them.
---

The fleet's own images are built by GitHub Actions from Dockerfiles in the repo, pushed to `ghcr.io/nikghodki/<name>`,
signed with **cosign keyless** (Sigstore) and given a signed SPDX SBOM (plan P3.5, decision 0008, runbooks/build-sign.md).
Kyverno admits `ghcr.io/nikghodki/*` only with this workflow's signature from `main` (policy `verify-images`, Enforce).

**Open user action:** the GHCR packages are still **private**, so Kyverno and the nodes get `UNAUTHORIZED` and every
`ghcr.io/nikghodki` image is refused until `mlflow` and `ros-zenoh` are made public in the GitHub UI (decision 0008;
the API can't change visibility).

| | |
|---|---|
| Workflow | `.github/workflows/build-sign.yml`; build spec per image in `.github/scripts/image-spec.sh` |
| Runs | on a push to `main` touching an image's files (or the workflow), or `workflow_dispatch` on `main`. Never on PRs |
| Runner | GitHub-hosted `ubuntu-24.04` (amd64); arm64 under QEMU (binfmt image pinned by digest) |
| Tools | buildx and cosign v3.1.4 as plain binaries pinned by SHA-256, BuildKit image by digest (only GitHub-owned actions are allowed in this repo, PR #63) |
| Platforms | `linux/amd64`, `linux/arm64` |
| Tags | the tag the host build already uses, plus `sha-<12 hex>`. Deploy by digest; tags are for people |
| Identity | `https://github.com/nikghodki/homelab/.github/workflows/build-sign.yml@refs/heads/main` |
| Issuer | `https://token.actions.githubusercontent.com` |
| SBOM | BuildKit SPDX (with files) + provenance per platform inside the signed index; plus the arm64 SPDX **at package level** as a signed cosign attestation (`spdxjson`). Rekor refuses entries over ~32 MB, and the ROS image's full SPDX is ~28 MB (PR #64) |
| Cache | registry cache `<image>:buildcache` |
| Permissions | workflow default `{}`; the job gets `contents: read`, `packages: write`, `id-token: write` |
| Retries | cosign sign/attest retried 4× on Fulcio/Rekor 5xx |
| Self-check | the run prints the certificate's subject and issuer, and fails if `cosign verify` accepts a wrong identity (`...@refs/heads/not-main`) |
| Measured | about 2 minutes per image (cold 1 min 54 s / 1 min 44 s, warm 1 min 42 s / 1 min 49 s): about 4 billed minutes per build of both |

## Images

| Image | Built from | Used by |
|---|---|---|
| `ghcr.io/nikghodki/mlflow` | `hosts/stacks/ml/mlflow/Dockerfile` (tag = the compose `image:` tag) | MLflow on dgx-2 (still built locally by compose) |
| `ghcr.io/nikghodki/ros-zenoh` | `hosts/roles/ros_zenoh_router/templates/Dockerfile.j2`, rendered with the role defaults | Zenoh router on the Jetson (still built locally by Ansible) |

Not built in CI: `robots/sim/mujoco` (~12 GB of CUDA wheels, close to a hosted runner's free disk; waits for the
self-hosted runner on dgx-2, P4.8).

## Verify

```bash
# on dgx-1
IMG=ghcr.io/nikghodki/ros-zenoh:kilted-1
ID=https://github.com/nikghodki/homelab/.github/workflows/build-sign.yml@refs/heads/main
cosign verify "$IMG" --certificate-identity "$ID" --certificate-oidc-issuer https://token.actions.githubusercontent.com
cosign verify-attestation "$IMG" --type spdxjson --certificate-identity "$ID" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com > /dev/null && echo SBOM ok
docker buildx imagetools inspect "$IMG"
```

A signature made anywhere else (a branch, a fork, a laptop) has a different identity and fails both `cosign verify`
and Kyverno.

## Add an image

1. A `case` branch in `.github/scripts/image-spec.sh` (`context`, `file`, and a `tag` read from wherever the image is
   already named). Test: `.github/scripts/image-spec.sh <name>`.
2. Add it to `matrix.image` and its paths to `on.push.paths`.
3. Pin the Dockerfile's `FROM` by digest, to a multi-arch index.
4. PR, merge; the push to `main` builds it.
5. Make the package public (or add a pull Secret), then reference it in `cluster/` by tag; Kyverno swaps in the
   verified digest (`mutateDigest`).

## Cost

Private repos on GitHub Free get 2,000 Actions minutes a month; arm64 hosted runners aren't included, hence QEMU. Builds
run only when an image's files change.
