#!/usr/bin/env bash
# Validate cluster/ manifests with kubeconform, and test them against policies/kyverno with the Kyverno CLI.
# Helm values files and SOPS-encrypted Secrets (*.enc.yaml) are skipped by kubeconform: values aren't manifests,
# and the `sops:` block isn't part of the Secret schema (check-sops.sh covers those files).
set -euo pipefail
KUBECONFORM_IMAGE="$1"; KYVERNO_IMAGE="$2"
manifests=$(find cluster -type f \( -name '*.yaml' -o -name '*.yml' \) 2>/dev/null | head -1)
if [ -z "$manifests" ]; then echo "no manifests under cluster/ yet"; exit 0; fi
docker run --rm -v "$PWD:/repo:ro" -w /repo "$KUBECONFORM_IMAGE" -strict -summary -ignore-missing-schemas \
  -ignore-filename-pattern '(^|/)values\.ya?ml$' -ignore-filename-pattern '\.enc\.ya?ml$' cluster/
if ! find policies/kyverno -type f \( -name '*.yaml' -o -name '*.yml' \) 2>/dev/null | grep -q .; then
  echo "no Kyverno policies under policies/kyverno/ yet"; exit 0
fi
kyverno() { docker run --rm -v "$PWD:/repo:ro" -w /repo "$KYVERNO_IMAGE" "$@"; }
# The CLI skips documents it can't parse with only a log line, so a broken policy would pass silently.
out=$(kyverno apply policies/kyverno --resource .github/scripts/fixtures/kyverno/bad-pod.yaml 2>&1 || true)
echo "$out"
if grep -qi 'parsing error' <<<"$out"; then echo "::error::a Kyverno policy failed to parse"; exit 1; fi
policies=$(grep -l '^kind: ValidatingPolicy' policies/kyverno/*.yaml | wc -l)
failed=$(grep -c '^policy .* -> resource default/Pod/bad-pod failed' <<<"$out" || true)
if [ "$failed" -ne "$policies" ]; then
  echo "::error::bad-pod fixture should fail all $policies policies, failed $failed"; exit 1
fi
kyverno apply policies/kyverno --resource cluster/ --policy-report
