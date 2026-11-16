# CI scanners: what runs, accepted findings, expiring ignores

`pr-checks.yml` runs on every PR and push to main; `nightly-scan.yml` runs at 01:17 PST. Everything runs on
GitHub-hosted runners (no home memory). Every tool image is pinned by digest and run with `docker run`; the lint job
fails if a `*_IMAGE:` in a workflow has no `@sha256:` (tags can be moved: in March 2026 a malicious Trivy v0.69.4,
Docker Hub tags 0.69.5/0.69.6 and 76 of 77 `trivy-action` tags were published; tool review 2026-11 §2.6).
Renovate bumps the digests.

| Concern | Tool | Where |
|---|---|---|
| Secrets in Git | gitleaks (full history), TruffleHog (verified only) | PR; gitleaks nightly too |
| Dependencies | OSV-Scanner (lockfiles), Trivy `fs` vulnerabilities | PR, nightly |
| Misconfigurations (Dockerfiles, Kubernetes, Compose) | Trivy `fs` misconfig, kubeconform + Kyverno CLI | PR |
| Images that run (CI tools, cluster, hosts) | Trivy `image`, vulnerabilities, CRITICAL | nightly |
| Shell | shellcheck over `*.sh` and shell `*.j2` templates (`.github/scripts/shellcheck.sh`) | PR (lint) |
| Code | Semgrep CE | PR |

Trivy runs **without its secret scanner** (`--scanners vuln,misconfig` for `fs`, `vuln` for images): gitleaks and
TruffleHog cover our secrets, and in third-party images Trivy's secret rules only matched docs and test data (all 9
"Phoenix" findings were `gcp-service-account` false positives in the Anthropic SDK's docstrings).

## shellcheck

`.github/scripts/shellcheck.sh <image@sha256>` checks tracked `*.sh` files and every `*.j2` template whose first line
is a `sh`/`bash` shebang, after stripping Jinja (`{{ x }}` becomes a word, `{% %}`/`{# #}` tags go). Warnings and
errors fail; info and style notes print but don't fail. Run it locally the same way:

```bash
.github/scripts/shellcheck.sh koalaman/shellcheck:v0.11.0@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d
```

## Accepted vulnerabilities (`.trivyignore.yaml`)

Findings with no fixed upstream image are accepted in `.trivyignore.yaml` under `vulnerabilities:`. Each entry:

- is scoped to the vulnerable package version with `purls` (a new image with the same CVE still fails),
- has a `statement` (why it is acceptable here),
- has an `expired_at` at most 30 days out.

`.github/scripts/check-trivy-ignores.py` checks this: the nightly fails on an **expired** entry; PRs check the
format and the 30-day limit only (`--no-expiry`), so a date passing doesn't block unrelated PRs.

When an entry expires (the nightly is red with `EXPIRED`):

1. Look for a fixed image (Renovate PR, or the upstream registry). If there is one, bump it and drop the entry.
2. If not, re-check that the reason still holds, then set a new `expired_at` (30 days) and update the statement.

The `misconfigurations:` entries (kube-vip, the tailnet externalIPs) are design decisions and don't expire.

### Accepted 2026-11-15 (expire 2026-12-15)

| CVE | Package | Images | Why accepted |
|---|---|---|---|
| CVE-2026-31789 | libcrypto3/libssl3 | gitleaks v8.30.1, actionlint 1.7.12, rest-server 0.14.0 | 32-bit only; all hosts and runners are 64-bit |
| CVE-2026-123158 | openssh client | gitleaks v8.30.1, Home Assistant 2026.11.1 | server-side bug; client only, no sshd |
| CVE-2026-119618 | apache2-utils | rest-server 0.14.0 | httpd mod_http2; only htpasswd is in the image |
| CVE-2025-68121 | Go stdlib crypto/tls | postgres 17.12-alpine (gosu), ksops v4.5.1, rest-server 0.14.0 | gosu and ksops do no TLS; rest-server has no client certs |
| CVE-2026-63825, -64523, -68426, -90162, -93221 | linux-libc-dev | ros:kilted-ros-base | kernel headers; containers use the host kernel |
| CVE-2026-96760 | Authlib 1.7.2 | Home Assistant 2026.11.1 | fixed in Authlib 1.9.0, in no HA release yet; take the HA release that has it |
| CVE-2026-85394 | python-jose 3.5.0 | Home Assistant 2026.11.1 | no fix anywhere yet; HA is LAN/tailnet only |

All of these were the newest release or digest on 2026-11-15. Fixed by a bump instead: dcgm-exporter 4.4.2-4.7.1 →
4.8.4 (gRPC CVE-2026-33186). Not 4.9.0: it renames the metrics and changes units (`DCGM_FI_DEV_GPU_TEMP` →
`DCGM_FI_DEV_GPU_TEMP_CELSIUS`, utilisation as a 0–1 ratio, ...), which the vmalert rules (`FleetGpuHot`,
`FleetGpuMetricsMissing`) and the Fleet Home dashboard read; Renovate holds it below 4.9 until they move. Phoenix's findings were secret-scanner false positives (above).
