# Image build and signing (`build-sign.yml`, plan P3.5)

The fleet's own images are built by GitHub Actions from the Dockerfiles in this repo, pushed to
`ghcr.io/nikghodki/<name>`, **signed with cosign keyless** and given a **signed SPDX SBOM**. Kyverno admits a
`ghcr.io/nikghodki/*` image only if it carries this workflow's signature from `main`
([kyverno.md](kyverno.md), policy `verify-images`). Why keyless and which images: [decision 0008](../decisions/0008-image-signing.md).

| | |
|---|---|
| Workflow | `.github/workflows/build-sign.yml`; build spec per image in `.github/scripts/image-spec.sh` |
| Runs | on a push to `main` that touches an image's files (or the workflow), and by hand (`workflow_dispatch`, `main` only). Never on pull requests |
| Runner | GitHub-hosted `ubuntu-24.04` (amd64); arm64 is built under QEMU (`tonistiigi/binfmt`) |
| Tools | the repo allows only GitHub-owned actions, so no docker/sigstore actions: buildx and cosign binaries are downloaded and checked against a SHA-256 in the workflow, binfmt and BuildKit run as images pinned by digest. Bump them together with their hash |
| Platforms | `linux/amd64`, `linux/arm64` |
| Tags | the tag the host build already uses (from `compose.yaml` / role defaults) and `sha-<12 hex of the commit>`. Deploy by digest; tags are for people |
| Signature | cosign v3 keyless: a Fulcio certificate for the workflow's GitHub OIDC token, logged in Rekor; no key to keep |
| Identity | `https://github.com/nikghodki/homelab/.github/workflows/build-sign.yml@refs/heads/main` |
| Issuer | `https://token.actions.githubusercontent.com` |
| SBOM | BuildKit SPDX (with every file) + provenance per platform inside the image index (covered by the signature), and the arm64 SPDX **at package level** (file list dropped) as a signed cosign attestation (`--type spdxjson`): Rekor refuses entries over ~32 MB and the ROS image's full SPDX is 28 MB |
| Permissions | workflow default `{}`; the build job gets `contents: read`, `packages: write`, `id-token: write` |
| Cache | BuildKit layer cache in the registry, tag `ghcr.io/nikghodki/<name>:buildcache` (written only by this job; not a runnable image) |

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

Measured 2026-11-15 (each job: tools, QEMU, build of both platforms, push, sign, SBOM attestation, verify):

| Run | mlflow | ros-zenoh |
|---|---|---|
| first (cold cache) | 1 min 54 s | 1 min 44 s (failed at the SBOM attestation, fixed by #64) |
| warm cache | 1 min 42 s | 1 min 49 s |

So a build of both images costs about 4 billed minutes (jobs round up to the minute).

## Built images (2026-11-15)

| Image | Digest (index: linux/amd64 + linux/arm64) | Tags |
|---|---|---|
| `ghcr.io/nikghodki/mlflow` | `sha256:ac9c9ca6befcb06384381b87619d6f71d886d610f2ec94690e7d6e5501fae8a0` | `3.18.0-psycopg2.9.13`, `sha-f5c4656542d7` |
| `ghcr.io/nikghodki/ros-zenoh` | `sha256:77e2acdc5628b45d35029a1ee243ab0bd3e4a9e7ad1e98461ec792cbfdd45e8d` | `kilted-1`, `sha-f5c4656542d7` |

Later builds move the tags; the run summary lists each build's digest and the verified certificate identity.

## Visibility

Packages pushed from this private repo start **private**: nodes and Kyverno can't read them without a credential
(runbooks/kyverno.md, "Private images"). For `mlflow` and `ros-zenoh` (nothing private inside) set them public:
github.com/nikghodki → Packages → `<name>` → Package settings → Danger zone → Change visibility → Public. The API
has no endpoint for this; it's a one-time click per package.
