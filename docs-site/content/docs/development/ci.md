---
title: CI
description: Every GitHub Actions workflow and job, what each checks, how tools are pinned, and how Renovate keeps them current.
---

Three workflows in `.github/workflows/`. Runners are GitHub-hosted `ubuntu-24.04`. Default permissions `contents: read`
(build-sign: `{}`); every checkout uses `persist-credentials: false`. Actions are pinned by commit SHA; tool images by
digest; Python tools from hash-locked files (`pip install --require-hashes`). Only GitHub-owned actions are allowed in
the repo settings (which is why build-sign uses plain buildx/cosign binaries, PR #63).

## `pr-checks.yml` (pull requests, daily on `main`, manual)

Two jobs, so two checks on every PR. GitHub bills each job rounded up to a whole minute, so the steps run in sequence
inside a job instead of as 8 parallel jobs (12-14 billable minutes a run before; infra-optimization review 2026-11 §4).
Each tool is still its own step with its own log. A step after a failed one still runs (`!cancelled()`), so one run
reports every failure, and any failed step fails the job.

| Check (job) | Steps | Fails on |
|---|---|---|
| `Checks (lint, docs, secrets, Kubernetes, unit tests)` (`checks`) | gitleaks 8.30.1 and TruffleHog 3.99.9 `--only-verified` on **the PR's own commits** (`base..head` of the merge commit; full history of `main` outside a PR); `check-sops.sh`; images pinned by digest; `edge-zone.py check`; `mkdocs build --strict`; yamllint 1.38.0 (`.yamllint.yaml`); actionlint 1.7.12; shellcheck; ansible-lint 26.11.0 on `playbooks/site.yml` and `roles`; kubeconform 0.8.0 + Kyverno CLI 1.20.0 (`check-kubernetes.sh`); pytest: fleet-metrics, LiteLLM guardrail and request hook, DefenseClaw fleet policy, Pocket ID sync, safety governor, motion bridge, Cisco AIBOM fleet job, MCP drift, DefenseClaw AIBOM diff, sim sampler, usage exporter, ops-agent host access, CI scripts; `defenseclaw-bundle.py check` | any finding or error |
| `Scans (code, dependencies, AI scanners, AIBOM)` (`scans`) | Semgrep 1.185.0 `p/default`; OSV-Scanner 2.7.1 (exit 128 = no manifests is OK); `.trivyignore.yaml` format and 30-day limit; Trivy 0.76.2 `fs` vuln and misconfig at HIGH/CRITICAL (no secret scanner); `mcp-tool-hashes.py check tools`; mcp-scanner 4.8.7; skill-scanner 2.3.2; a2a-scanner 1.0.1 (self-test, then the cards); Agentic Radar 0.14.2 in its own venv (artifact `agentic-radar`); Cisco AIBOM 1.10.1 in its own venv, deterministic (LLM at a closed port, run through `aibom-ci.py`), summary in the job summary, artifact `aibom` (30 days) | any finding (Radar never fails; AIBOM on errors only) |

- **Docs-only PRs** (every changed file under `docs/`, `docs-site/`, `runbooks/`, `decisions/`, or a `*.md` outside
  `agents/` and `tools/`; `.github/scripts/ci-scope.sh` decides and prints the file list) run only the secret scanners,
  SOPS, the digest-pin and edge-zone checks and the docs build, plus yamllint if they touch YAML. Both checks still
  report, and pass, so the check set is the same on every PR.
- **No run on a push to `main`**: a squash merge pushes the tree its PR run passed. The daily run at 08:47 UTC runs the
  full suite on `main` (merge skew shows within a day) and saves the caches. `build-sign.yml` still runs on pushes.
- **Caches**: the tool venvs, built by `.github/scripts/ci-venv.sh` from the hash-locked files with `--require-hashes`
  and keyed on the Python version and the lock files' hashes (a hit skips 20-25 s of installing per venv; a restored
  venv that fails `pip check` is rebuilt); `setup-python` `cache: pip` for the downloads when a venv is rebuilt; the Trivy DB per day, and the Ansible collections per day and `hosts/requirements.yml` (so new releases within
  its ranges still arrive within a day). A cache saved on a PR is visible to that PR
  only, which is why the daily run on `main` matters.
- **Concurrency**: a new push to a PR cancels that PR's older run; the daily and manual runs are never cancelled.
- **Secret scanning** reads only the PR's commits, so a false positive on another unmerged branch no longer fails
  unrelated PRs. `nightly-scan.yml` scans the full history of every branch with both gitleaks and TruffleHog.
- **AIBOM**: `aibom-ci.py` is `cisco-aibom` with its fixed 2 x 30 s retry cool-down set to 0: with no LLM a retry
  cannot succeed, and the report is identical.

## `nightly-scan.yml` (09:17 UTC daily, manual)

gitleaks and TruffleHog (verified) over the full history of every branch; OSV-Scanner for new advisories; Trivy (CRITICAL) on every `image:tag@sha256` in `.github/`,
`cluster/` and `hosts/` (compose stacks, role defaults; since #74), with one Trivy DB download for all images; the job
summary lists scan errors separately from CRITICAL findings (both fail the job); a CycloneDX SBOM of the repo. Not
`robots/` (the Isaac Lab base is too big for a hosted runner). Artifact `nightly-reports` (30 days).

## `build-sign.yml` (pushes to `main` touching image files, manual on `main`)

Builds `mlflow` and `ros-zenoh` for amd64 and arm64, pushes to GHCR, cosign keyless sign, SPDX attestation, verify.
See [Image signing](../platform/image-signing.md).

## Scripts (`.github/scripts/`)

| Script | Used by | Does |
|---|---|---|
| `ci-scope.sh` | both pr-checks jobs | the PR's commits for the secret scanners; docs-only or code |
| `check-sops.sh` | `checks` | plaintext checks for `secrets/` and `cluster/` |
| `check-kubernetes.sh` | `checks` | kubeconform + Kyverno CLI with the bad-pod fixture |
| `mcp-tool-hashes.py` | `scans` | `check` / `update` per-tool sha256 pins in `tools/*/tools.sha256` |
| `scan-mcp-tools.py` | `scans` | mcp-scanner on `tools/*/tools.json`, exit code from its JSON, accepted findings |
| `scan-skills.sh` | `scans` | skill-scanner on every `SKILL.md` folder in `agents/` and `tools/` |
| `scan-agents.py` | `scans` | a2a-scanner on `agents/*/card.yaml`; `--self-test` with `fixtures/unsafe-agent-card.json` |
| `scan-agent-code.sh` | `scans` | Agentic Radar for agents with `radar.yaml` |
| `export-mcp-tools.py` | people, on the host running a server | dump an MCP server's `tools/list` (stdio or HTTP), stdlib only |
| `defenseclaw-bundle.py` | `checks` (`check`), people (`sync`) | keep vendored DefenseClaw dashboards, rules and adapted configs in step with the pinned release |
| `ci-venv.sh` | both pr-checks jobs | a tool venv from a hash-locked file, or the cached one |
| `aibom-ci.py` | `scans` | cisco-aibom without the retry cool-down (no LLM in CI) |
| `image-spec.sh` | `build-sign.yml` | context, Dockerfile and tags per image |
| `tests/` | `checks` | tests for `defenseclaw-bundle.py` and the MCP scripts |

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
