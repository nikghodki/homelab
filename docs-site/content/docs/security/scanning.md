---
title: Scanning (CI and Cisco AIBOM)
description: What is scanned before a merge and nightly, the AI scanners and their quirks, and the Cisco AIBOM fleet inventory.
---

## In CI (every PR, and daily on `main`)

Workflow `.github/workflows/pr-checks.yml`. All third-party tools run as containers pinned by digest; Python tools are
installed from hash-locked files. Full job list: [CI](../development/ci.md).

| Check | Tool (version) | Fails on |
|---|---|---|
| Secrets in Git history | gitleaks 8.30.1 (the PR's commits, redacted; full history nightly) | any finding |
| Verified secrets | TruffleHog 3.99.9 (`--only-verified`) | a verified secret |
| SOPS | `.github/scripts/check-sops.sh` | plaintext in `secrets/`, plaintext `*.enc.yaml`, a Secret outside `*.enc.yaml` in `cluster/` |
| Code | Semgrep 1.185.0 (`p/default`) | any finding |
| Dependencies | OSV-Scanner 2.7.1 | a known vulnerability (exceptions in `.github/osv-scanner.toml`, each with an expiry) |
| Vulns, misconfig in files | Trivy 0.76.2 (`fs --scanners vuln,misconfig`, HIGH/CRITICAL; no secret scanner: gitleaks and TruffleHog cover secrets) | HIGH or CRITICAL |
| Shell | shellcheck 0.11.0 on `*.sh` and shell `*.j2` templates (`.github/scripts/shellcheck.sh`) | a warning or error |
| Kubernetes | kubeconform 0.8.0, Kyverno CLI 1.20.0 | invalid manifest; a policy that doesn't parse; the bad-pod fixture not failing every policy |
| MCP tools | `mcp-tool-hashes.py check`, mcp-scanner 4.8.7 (YARA, offline) | a changed tool without a hash update; HIGH/CRITICAL not accepted |
| Skills | skill-scanner 2.3.2 (`--policy strict --fail-on-severity high`) on any `SKILL.md` folder in `agents/`, `tools/` | HIGH or above (no skills in the repo yet) |
| Agent cards | a2a-scanner 1.0.1 (yara, heuristic, spec analyzers; plus a self-test on a known-bad card) | HIGH/CRITICAL |
| Agent code | Agentic Radar 0.14.2 (own venv) for agents with `radar.yaml` | never fails; HTML report artifact |
| AI BOM | Cisco AIBOM 1.10.1 on the repo, deterministic only | errors only; JSON artifact `aibom`, 30 days |
| Lint | actionlint, yamllint, ansible-lint | any error |

## Nightly (`nightly-scan.yml`, 09:17 UTC)

gitleaks over full history, OSV-Scanner for new advisories, Trivy (CRITICAL) on **every** `image@sha256` reference in
`.github/`, `cluster/` and `hosts/` (the compose stacks and role defaults, added in #74), and a CycloneDX SBOM of the
repo. A scan error (pull, registry, DB) is reported separately from CRITICAL findings; both fail the run. Reports are
an artifact for 30 days.

Not scanned nightly: images under `robots/` (the Isaac Lab base is too big for a hosted runner), images pinned by tag
only, and the hand-run containers on dgx-1.

## MCP tool pinning

Approved MCP servers live in `tools/<server>/` (`server.yaml`, `tools.json`, `tools.sha256`). The hash file is the
review record: a changed description or schema (tool poisoning, a "rug pull") has to show up as a diff in a reviewed
PR. Two servers, 44 tools. Details: [Agent cards and MCP tools](../agents/cards-and-tools.md).

## Scanner quirks

- **mcp-scanner 4.8.7 pins `litellm==1.93.2`**, which has two advisories (GHSA-7hp6-4w63-5g45, GHSA-g5ff-637f-6q2m). CI
  only imports it as a library for the offline YARA scan, so both are ignored in `.github/osv-scanner.toml` until
  2026-12-15. Relaxed on mcp-scanner's `main`, unreleased (upstream draft 08).
- **mcp-scanner always exits 0.** `scan-mcp-tools.py` reads its JSON report and sets the exit code.
- **Agentic Radar pins `rich<14`**, skill-scanner needs `rich>=14`: Radar gets its own venv and lock.
- **The Kyverno CLI skips policies it can't parse**, with only a log line. `check-kubernetes.sh` applies a pod that
  breaks every rule and fails unless every policy reports it.
- **Cisco AIBOM `analyze` requires an LLM.** CI and the fleet job point it at a closed port, so it falls back to its
  deterministic scanners (`agentic_status: degraded`). Expect some false positives.
- **skill-scanner inside DefenseClaw** needs `~/.local/bin` on the gateway's PATH, or it fails closed and quarantines
  every skill ([DefenseClaw](defenseclaw.md)).

## Cisco AIBOM fleet inventory

`cisco-aibom` inventories the AI parts of code and container images (models, agents, MCP servers and clients, skills,
prompts, datasets, endpoints, AI dependencies, secrets). Decision 0003; runbooks/aibom.md.

| | |
|---|---|
| Role / playbook | `cisco_aibom` / `playbooks/aibom.yml` |
| Install | `/opt/cisco-aibom/venv` from `.github/requirements-aibom.txt` (same universal lock as CI; rebuilt when the lock changes) |
| Unit | `cisco-aibom.timer` (~04:20 + up to 20 min; Jetson 01:30), `cisco-aibom.service` as root but read-only: `CapabilityBoundingSet=CAP_DAC_READ_SEARCH`, `ProtectSystem=strict`, `ProtectHome=read-only`, `Nice=19`, idle I/O, `OOMPolicy=continue` |
| Memory cap | Sparks 6G (`group_vars/sparks.yml`), Jetson 3G, Pi 1500M, default 4G |
| Memory guard | Sparks: skip an image target when MemAvailable is under 20 GiB (`aibom.skipped`). Code dirs always scanned |
| Remote images | The Jetson runs code-dir scans only; dgx-2 scans its images by digest (`cisco_aibom_remote_images`) and reports them as `host: jetson`, `scanned_on: dgx-2` |
| Reports | `/var/lib/cisco-aibom/<host>-<date>.json`, root only, 30 days |
| Summary | journal, `SyslogIdentifier=cisco-aibom` → Loki → Grafana "AI inventory" |

| Host | Code dirs | Container images |
|---|---|---|
| dgx-1 | `~/workspace/dgx-model-manager`, `/opt/homelab/litellm` | `litellm-proxy`, `open-webui` (both stopped since their move into k3s, 2026-11-16) |
| dgx-2 | — | `observe-phoenix-1` |
| Jetson | both Hermes checkouts, `~/workspace/roboclaw` | — |
| Pi | `/var/lib/picoclaw/.picoclaw`, `/var/lib/picoclaw/roboclaw`, `~/workspace/roboclaw` | — |

Per host, not central: secrets found in scanned code never leave the host; only counts and names go to Loki (secret
findings are counted, never named). dgx-2's Docker uses the containerd image store, so `docker save` fails there and
the job copies `/app`, `/opt`, `/srv` and the working dir out of a created (never started) container instead
(`"method": "docker-cp-fallback"`).

```bash
# run now on one host, from dgx-1 in hosts/
~/.venvs/ansible/bin/ansible <host> -b -m systemd_service -a "name=cisco-aibom.service state=started"
sudo journalctl -t cisco-aibom --since today -o cat | grep -E '"aibom.skipped"|"event": "aibom"'
```

Upgrade: bump `cisco-aibom` in `.github/requirements-aibom.in`, recompile (command in its header), let the `aibom` CI
job pass, merge, run `playbooks/aibom.yml`.
