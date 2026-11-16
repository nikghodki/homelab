---
title: CI
description: Every GitHub Actions workflow and job, what each checks, how tools are pinned, and how Renovate keeps them current.
---

Three workflows in `.github/workflows/`. Runners are GitHub-hosted `ubuntu-24.04`. Default permissions `contents: read`
(build-sign: `{}`); every checkout uses `persist-credentials: false`. Actions are pinned by commit SHA; tool images by
digest; Python tools from hash-locked files (`pip install --require-hashes`). Only GitHub-owned actions are allowed in
the repo settings (which is why build-sign uses plain buildx/cosign binaries, PR #63).

## `pr-checks.yml` (pull requests, pushes to `main`, manual)

| Job | Steps | Fails on |
|---|---|---|
| `lint` | actionlint 1.7.12; yamllint 1.38.0 with `.yamllint.yaml` (line length 160 as a warning, no document-start, octal values forbidden); ansible-lint 26.11.0 on `playbooks/site.yml` and `roles` | any error |
| `secrets` | gitleaks 8.30.1 on the full history (redacted); TruffleHog 3.99.9 `--only-verified`; `check-sops.sh` | any finding |
| `code` | Semgrep 1.185.0 `p/default`; OSV-Scanner 2.7.1 (exit 128 = no manifests is OK); Trivy 0.76.2 `fs` vuln and misconfig (no secret scanner) at HIGH/CRITICAL; `.trivyignore.yaml` format and 30-day limit | any finding |
| `kubernetes` | `check-kubernetes.sh`: kubeconform 0.8.0 `-strict` on `cluster/` (values files and `*.enc.yaml` skipped); Kyverno CLI 1.20.0 with a bad-pod fixture that must fail every policy; then `cluster/` against the policies | invalid manifests, unparsed or non-failing policies |
| `ai-scanners` | `mcp-tool-hashes.py check tools`; `scan-mcp-tools.py tools` (mcp-scanner 4.8.7); `scan-skills.sh` (skill-scanner 2.3.2); `scan-agents.py --self-test` then `scan-agents.py` (a2a-scanner 1.0.1); Agentic Radar 0.14.2 in its own venv (report artifact) | hash drift, HIGH/CRITICAL findings |
| `aibom` | Cisco AIBOM 1.10.1 in its own venv on the repo, deterministic (LLM at a closed port); summary in the job summary; artifact `aibom` (30 days) | tool errors |
| `unit-tests` | pytest: fleet-metrics, LiteLLM guardrail, DefenseClaw fleet policy (and the MCP registry vs `server.yaml`), Pocket ID sync, safety governor, robot motion bridge, Cisco AIBOM fleet job, MCP drift check, CI scripts; `defenseclaw-bundle.py check` (vendored dashboards and rules match the release) | any failure |

`concurrency` cancels older runs of the same ref.

## `nightly-scan.yml` (09:17 UTC daily, manual)

gitleaks over full history; OSV-Scanner for new advisories; Trivy (CRITICAL) on every `image:tag@sha256` in `.github/`,
`cluster/` and `hosts/` (compose stacks, role defaults; since #74), with one Trivy DB download for all images; the job
summary lists scan errors separately from CRITICAL findings (both fail the job); a CycloneDX SBOM of the repo. Not
`robots/` (the Isaac Lab base is too big for a hosted runner). Artifact `nightly-reports` (30 days).

## `build-sign.yml` (pushes to `main` touching image files, manual on `main`)

Builds `mlflow` and `ros-zenoh` for amd64 and arm64, pushes to GHCR, cosign keyless sign, SPDX attestation, verify.
See [Image signing](../platform/image-signing.md).

## Scripts (`.github/scripts/`)

| Script | Used by | Does |
|---|---|---|
| `check-sops.sh` | `secrets` job | plaintext checks for `secrets/` and `cluster/` |
| `check-kubernetes.sh` | `kubernetes` job | kubeconform + Kyverno CLI with the bad-pod fixture |
| `mcp-tool-hashes.py` | `ai-scanners` | `check` / `update` per-tool sha256 pins in `tools/*/tools.sha256` |
| `scan-mcp-tools.py` | `ai-scanners` | mcp-scanner on `tools/*/tools.json`, exit code from its JSON, accepted findings |
| `scan-skills.sh` | `ai-scanners` | skill-scanner on every `SKILL.md` folder in `agents/` and `tools/` |
| `scan-agents.py` | `ai-scanners` | a2a-scanner on `agents/*/card.yaml`; `--self-test` with `fixtures/unsafe-agent-card.json` |
| `scan-agent-code.sh` | `ai-scanners` | Agentic Radar for agents with `radar.yaml` |
| `export-mcp-tools.py` | people, on the host running a server | dump an MCP server's `tools/list` (stdio or HTTP), stdlib only |
| `defenseclaw-bundle.py` | `unit-tests` (`check`), people (`sync`) | keep vendored DefenseClaw dashboards, rules and adapted configs in step with the pinned release |
| `image-spec.sh` | `build-sign.yml` | context, Dockerfile and tags per image |
| `tests/` | `unit-tests` | tests for `defenseclaw-bundle.py` and the MCP scripts |

## Pinned tool locks

| File | Tools | Compile with |
|---|---|---|
| `.github/requirements-ci.in` → `.txt` | yamllint, ansible-lint, cisco-ai-mcp-scanner, cisco-ai-skill-scanner, pytest, httpx, cisco-ai-a2a-scanner | `uv pip compile --generate-hashes --python-version 3.12 --python-platform x86_64-manylinux_2_28 .github/requirements-ci.in -o .github/requirements-ci.txt` |
| `.github/requirements-aibom.in` → `.txt` | `cisco-aibom[agentic,llm-openai,analysis]` (universal lock: also used on the aarch64 hosts) | `uv pip compile --universal --generate-hashes --python-version 3.12 ...` |
| `.github/requirements-radar.in` → `.txt` | agentic-radar, pyyaml | like requirements-ci |
| `hosts/roles/safety_governor/files/requirements-cli.txt` | nats-py (hash-locked, for dgx-1's operator CLI) | by hand |
| `hosts/stacks/ml/mlflow/requirements.txt` | psycopg2-binary (hashes) | by hand |

OSV exceptions (`.github/osv-scanner.toml`) apply to the CI lock only, each with `ignoreUntil` (two LiteLLM advisories
via mcp-scanner's pin, until 2026-12-15).

## Renovate

Weekly (Monday before 06:00 PT), at most 5 PRs, CI tools grouped, digests and SHAs pinned, lock file maintenance; the
DefenseClaw bundle bump needs a manual `sync` first. Details: [Upgrades](../operations/upgrades.md).

## Running checks locally (on dgx-1)

```bash
cd ~/homelab-wt/<branch>
(cd hosts && ~/.venvs/ansible/bin/ansible-lint playbooks/site.yml roles)
(cd robots/safety/governor && PYTHONPATH=. python3 -m pytest -q tests)
(cd hosts/files/fleet-metrics && python3 -m pytest -q)
```

yamllint and pytest may not be in the Ansible venv (unverified); install them from `.github/requirements-ci.txt` in a scratch venv if needed. The container-based scanners (gitleaks, Trivy, ...) can run with `docker run` and the same image references as the
workflow, but CI is the authority.
