# Upstream issue drafts

These are drafts only. Nothing here has been posted, and the user decides what to post. Each file has the title,
version, environment, steps, expected and actual behaviour, evidence (file:line in the 1.0.9 source), a suggested fix
and our workaround.

Upstream was checked on 2026-11-15. The latest DefenseClaw release is 1.0.9 (2026-11-12), and `main` has three commits
since, none of them related. The latest mcp-scanner release is 4.8.7.

| # | Issue | Target repo | Status | File |
|---|---|---|---|---|
| 1 | Edge Connector doesn't build against mbedTLS 3.6 (`mbedtls_ssl_conf_min_version` deprecated + `-Werror`) | cisco-ai-defense/defenseclaw | Draft (not reported; still on `main`) | [01](01-edge-connector-mbedtls-3.6.md) |
| 2 | OSS Fleet gateway blocks every escalated hash; no allow API or configurable verdict pipeline | cisco-ai-defense/defenseclaw | Draft (feature request; default-deny is documented in the edge README) | [02](02-fleet-default-deny-no-allow-api.md) |
| 3 | picoclaw tools missing from the C tool table; `picoclaw_hook.py` is FFI-only | cisco-ai-defense/defenseclaw | Hook part in open PR #1343 (unmerged); tool table not reported | [03](03-edge-connector-picoclaw-tools-and-socket-hook.md) |
| 4 | Fleet gateway MQTT client is MQTT 5 only; docs say 3.1.1 | cisco-ai-defense/defenseclaw | Draft (not reported) | [04](04-fleet-mqtt5-only-docs-say-3.1.1.md) |
| 5 | `policy edit scanner -p` writes lowercase severity keys next to uppercase | cisco-ai-defense/defenseclaw | Draft (not reported; still on `main`) | [05](05-policy-edit-scanner-lowercase-keys.md) |
| 6 | Hermes connector: one HERMES_HOME per account; second profile stops the gateway | cisco-ai-defense/defenseclaw | Draft (not reported; add the exact error line before posting) | [06](06-hermes-connector-single-hermes-home.md) |
| 7 | `skill-scanner` not found under a systemd user unit → every skill quarantined; `skill restore` fails | cisco-ai-defense/defenseclaw | Draft (not reported; related #796 closed, #1428 open) | [07](07-skill-scanner-path-fail-closed-quarantine.md) |
| 8 | mcp-scanner 4.8.7 pins `litellm==1.93.2` (GHSA-7hp6-4w63-5g45, GHSA-g5ff-637f-6q2m) | cisco-ai-defense/mcp-scanner | Relaxed on `main` (#289), unreleased; floor PRs #290, #295, #315 open. Comment, don't file | [08](08-mcp-scanner-litellm-pin.md) |
| 9 | cisco-aibom 1.10.1: `MLLifecycleDetector` re-searches the whole file per line of Python (quadratic; ~75 min for Hermes) | cisco-ai-defense/aibom | Draft (not reported; still on `main`) | [09](09-cisco-aibom-ml-lifecycle-quadratic.md) |

When one is posted, put the upstream link in its file and in this table. When a release fixes one, update its runbook
and the "Known limits" sections (`runbooks/edge-connector.md`, `policies/README.md`, `.github/osv-scanner.toml`).
