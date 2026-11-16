---
title: "Upgrades"
description: "How versions move: Renovate PRs, the DefenseClaw bundle sync, k3s and Helm charts, host OS updates, and the hand-run pieces Renovate can't see."
---

## Renovate (`renovate.json`)

| Setting | Value |
|---|---|
| Presets | `config:recommended`, `helpers:pinGitHubActionDigests`, `docker:pinDigests`, `:dependencyDashboard` |
| Schedule | before 06:00 on Monday, America/Los_Angeles; lock file maintenance on the same schedule |
| Limits | 5 open PRs, label `renovate` |
| Custom managers | images used with `docker run` in workflows (`image:tag@sha256:...`); the DefenseClaw release in `hosts/stacks/observe/defenseclaw-bundle.yaml` |
| Groups | everything under `.github/` is one "CI tools" PR |
| DefenseClaw | no automerge; the PR body says to run `defenseclaw-bundle.py sync` on dgx-1 first |
| pip | `pip-compile` for `.github/requirements-ci.txt` and `requirements-aibom.txt`; plain `pip_requirements` off |

Renovate PRs follow the same rules as any PR: merge only on green, then deploy what they touch (a compose image bump
needs its stack's playbook; a chart bump in `cluster/` deploys itself).

What Renovate covers: compose images (digest-pinned), GitHub Actions (SHA-pinned), workflow tool images, Helm chart
versions in `cluster/bootstrap/apps/` (unverified that Renovate detects these Application manifests), the hash-locked
Python files.

What it **doesn't** see: the front door (`caddy:2.11` tag), `nginx:alpine`, Home Assistant (`stable`), LiteLLM, Open
WebUI, DGXMM (all hand-run); the k3s version and checksums (`roles/k3s/defaults`); the OTel collector version
(`otel_host_collector_version`); restic (`restic_install_version`); the ROS base image digest
(`ros_zenoh_router_base_image`); the Isaac Lab and MuJoCo images; DefenseClaw per-user installs and the Edge Connector.

## DefenseClaw

1. Renovate bumps `version` in `defenseclaw-bundle.yaml`.
2. On dgx-1, on that branch: `.github/scripts/defenseclaw-bundle.py sync` (copies verbatim dashboards and rules; prints
   upstream diffs for `loki.yaml`, `tempo.yaml`, the otel-defenseclaw config); port the diffs; update `adapted_base`;
   push. CI `defenseclaw-bundle.py check` must pass.
3. Merge; `playbooks/observe.yml`.
4. Per-user installs (Jetson ×2, dgx-1) with the release installer, as each user; rebuild the Edge Connector on the Pi
   from the same release; upgrade gateway and devices together.
5. `playbooks/defenseclaw.yml` (policy, PATH, Fleet settings); `chmod -R go-w ~/.local/share/uv ~/.defenseclaw/.venv ~/.defenseclaw/installer`
   on dgx-1 if uv installed a new Python.
6. Check the upstream drafts in `docs/upstream-issues/` against the release notes; update "Known limits".

## k3s

Set `k3s_version`, `k3s_sha256` (both arches) and `k3s_install_script_sha256` in `roles/k3s/defaults/main.yml`; one minor
version at a time; snapshot first; `playbooks/k3s.yml` (dgx-2, then dgx-1 and the Jetson one at a time, then Omarchy).

## Argo CD, Kyverno, CNPG

Bump `targetRevision` in `cluster/bootstrap/apps/<app>.yaml` after reading the upgrade notes and running `helm template`
with the values. Argo CD upgrades itself on merge.

## Host OS

- The Jetson and the Pi take security updates automatically (no reboot). The Sparks don't (NVIDIA turns unattended
  upgrades off); apply them with `playbooks/hardening.yml --limit <spark> --tags all,security_updates`.
- Jetson, open operator actions from Lynis: a reboot (KRNL-5830) and `sudo apt-get install linux-firmware` + reboot
  (PKGS-7392), in the monthly window.
- Full updates and reboots in the monthly window: back up and snapshot → Omarchy → Jetson → dgx-2 → dgx-1 → Pi (docked).
- Before rebooting a Spark, make sure the Jetson is healthy (it's the third etcd vote).
- Omarchy needed a full system update before Tailscale would install (P0.10).

## Cisco AIBOM, CI tools

Bump the `.in` file, recompile with the command in its header (uv pip compile ... `--generate-hashes`), let CI pass,
merge; for AIBOM also `playbooks/aibom.yml` (the venv is rebuilt when the lock changes).
