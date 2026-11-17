#!/usr/bin/env bash
# The Ask Me overlay (cluster/apps/open-webui/image, runbooks/open-webui.md) still builds on its pinned upstream
# image: a PR that changes the overlay (a Renovate bump of the FROM line, or the patch) builds it here, so a patch
# that no longer applies fails the PR instead of the build-sign run on main. linux/amd64 (native on the runner; the
# Python and HTML files the patch edits are the same in the arm64 image that build-sign builds). The image is
# thrown away. Other PRs and the daily run skip it (the base is pinned by digest, nothing can change under it).
#   .github/scripts/open-webui-overlay-check.sh [<base commit>]
set -euo pipefail
dir=cluster/apps/open-webui/image
base="${1:-}"
if [ -z "$base" ]; then
  if [ "${GITHUB_EVENT_NAME:-}" = schedule ]; then echo "daily run: skipped (the base image is pinned by digest)"; exit 0; fi
elif git diff --quiet "$base" HEAD -- "$dir" "$0"; then
  echo "nothing under $dir changed: skipped"; exit 0
fi
tag=askme-overlay-check:ci
if ! docker build --platform linux/amd64 --pull --progress plain -t "$tag" "$dir"; then
  echo "::error file=$dir/Dockerfile::the Ask Me overlay doesn't build on this base; if patch_branding.py says the patch no longer applies, read the new upstream files and update it"
  exit 1
fi
# What the running app reads: the name without a suffix, the page title, the licence next to the app
if ! docker run --rm --network none --entrypoint python3 "$tag" -c '
import pathlib, sys
env = pathlib.Path("/app/backend/open_webui/env.py").read_text()
html = pathlib.Path("/app/build/index.html").read_text()
bad = []
if "(Open WebUI)'"'"'" in env: bad.append("env.py still appends (Open WebUI)")
if "<title>Ask Me</title>" not in html: bad.append("index.html title is not Ask Me")
if not pathlib.Path("/app/LICENSE.open-webui").is_file(): bad.append("/app/LICENSE.open-webui missing")
print("\n".join(bad) or "overlay ok: no suffix, title Ask Me, licence present"); sys.exit(1 if bad else 0)
'; then
  echo "::error file=$dir/Dockerfile::the overlay built but its result is wrong (above)"; exit 1
fi
docker image rm "$tag" > /dev/null
