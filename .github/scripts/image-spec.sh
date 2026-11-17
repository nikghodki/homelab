#!/usr/bin/env bash
# Build spec for one image of build-sign.yml (runbooks/build-sign.md): prints `context=`, `file=` and `tags=` lines
# for $GITHUB_OUTPUT. The tag comes from the file that already names the image locally, so CI and the host builds
# carry the same tag; the commit tag (sha-<12>) makes every build addressable.
# An image built for fewer platforms than the workflow's PLATFORMS prints a `platforms=` line too.
#   .github/scripts/image-spec.sh <name> [<git sha>]
set -euo pipefail
name="${1:?image name}"; sha="${2:-$(git rev-parse HEAD)}"
registry="ghcr.io/nikghodki"
# value of `key: value` in a YAML file, quotes and trailing comments stripped (simple scalars only)
yaml_value() { sed -n -E "s/^[[:space:]]*$2:[[:space:]]*\"?([^\"#]*[^\"#[:space:]])\"?.*$/\1/p" "$1" | head -1; }
case "$name" in
  mlflow)
    context=hosts/stacks/ml/mlflow
    file="$context/Dockerfile"
    # compose.yaml: `image: homelab/mlflow:<tag>` under the mlflow service
    tag=$(sed -n -E "s#^[[:space:]]*image:[[:space:]]*homelab/mlflow:([^[:space:]]+).*#\1#p" hosts/stacks/ml/compose.yaml | head -1)
    ;;
  ros-zenoh)
    # The Dockerfile is an Ansible template; render its two variables from the role defaults.
    defaults=hosts/roles/ros_zenoh_router/defaults/main.yml
    base=$(yaml_value "$defaults" ros_zenoh_router_base_image)
    distro=$(yaml_value "$defaults" ros_zenoh_router_distro)
    tag=$(yaml_value "$defaults" ros_zenoh_router_image_tag); tag="${tag##*:}"
    context=$(mktemp -d); file="$context/Dockerfile"
    sed -e "s#{{ ros_zenoh_router_base_image }}#$base#g" -e "s#{{ ros_zenoh_router_distro }}#$distro#g" \
      hosts/roles/ros_zenoh_router/templates/Dockerfile.j2 > "$file"
    if grep -q "{{" "$file"; then echo "unrendered template variable in $file" >&2; exit 1; fi
    ;;
  ops-agent)
    # The ops agent (decision 0013): tag = the version in its pyproject.toml.
    context=agents/ops-agent
    file="$context/Dockerfile"
    tag=$(sed -n -E 's/^version = "([^"]+)"/\1/p' agents/ops-agent/pyproject.toml | head -1)
    ;;
  open-webui)
    # Ask Me, the Open WebUI overlay (runbooks/open-webui.md): tag = the upstream tag of the Dockerfile's FROM plus
    # -askme.<revision> (the `# askme-revision:` line). arm64 only: it runs on dgx-1, and the base is ~2 GB per platform.
    context=cluster/apps/open-webui/image
    file="$context/Dockerfile"
    tag=""
    upstream=$(sed -n -E 's#^FROM[[:space:]]+ghcr\.io/open-webui/open-webui:([^@[:space:]]+)@sha256:[a-f0-9]{64}([[:space:]].*)?$#\1#p' "$file" | head -1)
    rev=$(sed -n -E 's/^# askme-revision: ([0-9]+)$/\1/p' "$file" | head -1)
    if [ -n "$upstream" ] && [ -n "$rev" ]; then tag="$upstream-askme.$rev"; fi
    platforms=linux/arm64
    ;;
  *) echo "unknown image: $name" >&2; exit 1 ;;
esac
if [ -z "$tag" ]; then echo "no tag found for $name" >&2; exit 1; fi
echo "context=$context"
echo "file=$file"
echo "image=$registry/$name"
echo "tags=$registry/$name:$tag,$registry/$name:sha-${sha:0:12}"
if [ -n "${platforms:-}" ]; then echo "platforms=$platforms"; fi
