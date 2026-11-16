#!/usr/bin/env bash
# ci-venv.sh <dir> <requirements.txt> [pip args...]: the venv at <dir> with the hash-locked <requirements.txt>.
# pr-checks.yml restores the venvs from actions/cache (key: Python version + hash of the lock files; the daily run on
# main saves them for every PR). A restored venv is used as is if its Python runs and pip finds nothing missing or
# broken; otherwise it is rebuilt with --require-hashes (a cache hit skips about 20-25 s of installing per venv).
set -euo pipefail
dir=$1 req=$2; shift 2
if [ -x "$dir/bin/python" ] && "$dir/bin/python" -m pip check -q >/dev/null 2>&1; then
  echo "$dir: restored from the cache ($("$dir/bin/python" -m pip list --format=freeze 2>/dev/null | wc -l) packages)"
  exit 0
fi
echo "$dir: building from $req"
rm -rf "$dir"
python3 -m venv "$dir"
"$dir/bin/pip" install -q --require-hashes "$@" -r "$req"
