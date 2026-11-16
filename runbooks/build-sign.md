# Image build and signing (`build-sign.yml`, plan P3.5)

The fleet's own images are built by GitHub Actions from the Dockerfiles in this repo, pushed to
`ghcr.io/nikghodki/<name>`, **signed with cosign keyless** and given a **signed SPDX SBOM**. Kyverno admits a
`ghcr.io/nikghodki/*` image only if it carries this workflow's signature from `main`
([kyverno.md](kyverno.md), policy `verify-images`). Why keyless and which images: [decision 0008](../decisions/0008-image-signing.md).

| | |
|---|---|
| Workflow | `.github/workflows/build-sign.yml`; build spec per image in `.github/scripts/image-spec.sh` |
| Runs | on a push to `main` that touches an image's files (or the workflow), and by hand (`workflow_dispatch`, `main` only). Never on pull requests |
| Runner | GitHub-hosted `ubuntu-24.04` (amd64); arm64 is built under QEMU (`docker/setup-qemu-action`) |
| Platforms | `linux/amd64`, `linux/arm64` |
| Tags | the tag the host build already uses (from `compose.yaml` / role defaults) and `sha-<12 hex of the commit>`. Deploy by digest; tags are for people |
| Signature | cosign v3 keyless: a Fulcio certificate for the workflow's GitHub OIDC token, logged in Rekor; no key to keep |
| Identity | `https://github.com/nikghodki/homelab/.github/workflows/build-sign.yml@refs/heads/main` |
| Issuer | `https://token.actions.githubusercontent.com` |
| SBOM | BuildKit SPDX + provenance per platform inside the image index (covered by the signature), and the arm64 SPDX as a signed cosign attestation (`--type spdxjson`) |
| Permissions | workflow default `{}`; the build job gets `contents: read`, `packages: write`, `id-token: write` |
| Cache | BuildKit layer cache in the Actions cache (`type=gha`, one scope per image) |

## Images

| Image | Built from | Used by |
|---|---|---|
| `ghcr.io/nikghodki/mlflow` | `hosts/stacks/ml/mlflow/Dockerfile` (tag = compose `image:` tag) | MLflow on dgx-2 (still built locally by compose; the k3s move is P3.7) |
| `ghcr.io/nikghodki/ros-zenoh` | `hosts/roles/ros_zenoh_router/templates/Dockerfile.j2`, rendered with the role defaults (tag = `ros_zenoh_router_image_tag`) | Zenoh router on the Jetson (still built locally by Ansible) |

**Not built in CI:** `robots/sim/mujoco` (~12 GB: JAX CUDA 13 wheels). A hosted runner has about 14 GB of free disk,
the arm64 half would run under QEMU, and the push alone would take most of a run; decision 0008. It stays a local
build on the Sparks until the self-hosted runner on dgx-2 (P4.8) exists; then add it to the matrix with
`runs-on: [self-hosted, ...]` (the signing identity is the workflow, not the runner, so the policy doesn't change).

## Add an image

1. Add a `case` branch to `.github/scripts/image-spec.sh`: `context`, `file`, and a `tag` read from wherever the
   image is already named (one source of truth). Check it: `.github/scripts/image-spec.sh <name>`.
2. Add the name to `matrix.image` and its paths to `on.push.paths` in `build-sign.yml`.
3. Keep the Dockerfile's `FROM` pinned by digest, to a multi-arch index if both platforms are built
   (`docker buildx imagetools inspect <base>` lists the platforms).
4. PR, merge; the push to `main` builds it. The run summary shows the digest.
5. Reference it in `cluster/` **by tag**; Kyverno replaces the tag with the verified digest at admission
   (`mutateDigest`). A `@sha256:` reference is fine too.

## Verify an image

```bash
# on dgx-1 (cosign: ~/.local/bin; ghcr credentials only needed while the package is private)
IMG=ghcr.io/nikghodki/ros-zenoh:kilted-1
cosign verify "$IMG" \
  --certificate-identity https://github.com/nikghodki/homelab/.github/workflows/build-sign.yml@refs/heads/main \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com | jq -r '.[0].optional | .Subject, .githubWorkflowSha'
cosign verify-attestation "$IMG" --type spdxjson \
  --certificate-identity https://github.com/nikghodki/homelab/.github/workflows/build-sign.yml@refs/heads/main \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com > /dev/null && echo SBOM attestation ok
docker buildx imagetools inspect "$IMG"            # digest and platforms
```

A signature made anywhere else (a branch, a fork, a laptop with `cosign sign`) has a different identity and fails
both `cosign verify` and Kyverno.

## Minutes and storage (GitHub Free, decision 0001)

Private repos on Free get **2,000 Actions minutes a month** (Linux 1x) and arm64 hosted runners aren't included,
hence QEMU on `ubuntu-24.04`. A cold build of both images measured on the first run is in the table below; cached
rebuilds of an unchanged image are a couple of minutes. Builds only run when an image's files change, so normal use
is far below the quota. GHCR storage and transfer for container images are currently not billed.

| Run | mlflow | ros-zenoh |
|---|---|---|
| first (cold cache) | see PR | see PR |
