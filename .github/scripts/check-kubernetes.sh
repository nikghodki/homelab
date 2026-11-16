#!/usr/bin/env bash
# Validate cluster/ manifests with kubeconform, and test them against policies/kyverno with the Kyverno CLI.
# Helm values files and SOPS-encrypted Secrets (*.enc.yaml) are skipped by kubeconform: values aren't manifests,
# and the `sops:` block isn't part of the Secret schema (check-sops.sh covers those files).
set -euo pipefail
KUBECONFORM_IMAGE="$1"; KYVERNO_IMAGE="$2"
# -print -quit, not `| head -1` / `| grep -q`: with pipefail, find's SIGPIPE on a big tree fails the pipeline
manifests=$(find cluster -type f \( -name '*.yaml' -o -name '*.yml' \) -print -quit 2>/dev/null)
if [ -z "$manifests" ]; then echo "no manifests under cluster/ yet"; exit 0; fi
docker run --rm -v "$PWD:/repo:ro" -w /repo "$KUBECONFORM_IMAGE" -strict -summary -ignore-missing-schemas \
  -ignore-filename-pattern '(^|/)values\.ya?ml$' -ignore-filename-pattern '\.enc\.ya?ml$' cluster/
if [ -z "$(find policies/kyverno -type f \( -name '*.yaml' -o -name '*.yml' \) -print -quit 2>/dev/null)" ]; then
  echo "no Kyverno policies under policies/kyverno/ yet"; exit 0
fi
fixture=$(mktemp -d); chmod 755 "$fixture"; trap 'rm -rf "$fixture"' EXIT
kyverno() { docker run --rm -v "$PWD:/repo:ro" -v "$fixture:/fixture:ro" -w /repo "$KYVERNO_IMAGE" "$@"; }
# The CLI skips documents it can't parse with only a log line, so a broken policy would pass silently. A pod that
# breaks every policy must be reported by each of them. (Written here, not committed, so Trivy doesn't flag it.)
cat > "$fixture/bad-pod.yaml" <<'POD'
apiVersion: v1
kind: Pod
metadata: {name: bad-pod, namespace: default}
spec:
  hostNetwork: true
  containers:
    - name: app
      image: evil.example.com/app:latest
      securityContext: {privileged: true}
POD
chmod 644 "$fixture/bad-pod.yaml"
out=$(kyverno apply policies/kyverno --resource /fixture/bad-pod.yaml 2>&1 || true)
echo "$out"
if grep -qi 'parsing error' <<<"$out"; then echo "::error::a Kyverno policy failed to parse"; exit 1; fi
policies=$(grep -l '^kind: ValidatingPolicy' policies/kyverno/*.yaml | wc -l)
failed=$(grep -c '^policy .* -> resource default/Pod/bad-pod failed' <<<"$out" || true)
if [ "$failed" -ne "$policies" ]; then
  echo "::error::bad-pod fixture should fail all $policies policies, failed $failed"; exit 1
fi
kyverno apply policies/kyverno --resource cluster/ --policy-report
