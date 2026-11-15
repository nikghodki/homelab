#!/usr/bin/env bash
# Validate cluster/ manifests with kubeconform, and test them against policies/kyverno with the Kyverno CLI.
# Does nothing until those folders contain YAML.
set -euo pipefail
KUBECONFORM_IMAGE="$1"; KYVERNO_IMAGE="$2"
manifests=$(find cluster -type f \( -name '*.yaml' -o -name '*.yml' \) 2>/dev/null | head -1)
if [ -z "$manifests" ]; then echo "no manifests under cluster/ yet"; exit 0; fi
docker run --rm -v "$PWD:/repo:ro" -w /repo "$KUBECONFORM_IMAGE" -strict -summary -ignore-missing-schemas cluster/
if find policies/kyverno -type f \( -name '*.yaml' -o -name '*.yml' \) 2>/dev/null | grep -q .; then
  docker run --rm -v "$PWD:/repo:ro" -w /repo "$KYVERNO_IMAGE" apply policies/kyverno --resource cluster/ --policy-report
else
  echo "no Kyverno policies under policies/kyverno/ yet"
fi
