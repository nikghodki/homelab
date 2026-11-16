---
title: "Deploying"
description: "How a change reaches the hosts (Ansible: check, real, second run) and the cluster (GitOps), with the gotchas that bit before."
---

## Host changes (Ansible)

```bash
# on dgx-1, from a checkout of main (after the PR merged) or your rebased worktree
source ~/.venvs/ansible/bin/activate && cd ~/homelab/hosts
~/.venvs/ansible/bin/ansible-galaxy collection install -r requirements.yml    # once
ansible-playbook playbooks/<name>.yml --check --diff            # 1. what would change
ansible-playbook playbooks/<name>.yml [--limit <host>]           # 2. apply
ansible-playbook playbooks/<name>.yml --check --diff            # 3. idempotent: no changes
```

Collections: community.general, ansible.posix, community.docker, community.sops (`hosts/requirements.yml`).
`ansible.cfg`: inventory `inventory.yml`, `pipelining = true`, 5 forks, YAML output.

### Playbooks

| Playbook | Hosts | Does |
|---|---|---|
| `site.yml` | all | `base`, `hardening`, `tailscale`, `fleet_metrics`, then imports `always-on.yml` |
| `hardening.yml` | all | role `hardening` (Lynis remediation; `--tags all,security_updates` opt-in) |
| `always-on.yml` | `always_on` (Dell) | role `always_on` |
| `pki.yml` | all | role `homelab_ca` (both CAs) |
| `fleet-metrics.yml` | all | role `fleet_metrics` |
| `collectors.yml` | all | role `otel_host_collector` (+ Fleet API token on dgx-1) |
| `lynis.yml` | all | role `lynis` |
| `aibom.yml` | all | role `cisco_aibom` (only where enabled) |
| `defenseclaw.yml` | all | `defenseclaw_policy`, `defenseclaw_gateway_env`, `defenseclaw_fleet`, `defenseclaw_aibom` |
| `edge-connector.yml` | `edge` (Pi) | role `edge_connector` |
| `bus.yml` | `bus` (dgx-1) | stack `bus`; operator safety CLI |
| `fleet.yml` | `bus` (dgx-1) | stack `fleet` |
| `gpu.yml` | `sparks`; `jetson_group` | stack `gpu`; role `jetson_cdi` |
| `observe.yml` | `observe` (dgx-2) | stack `observe` |
| `console.yml` | `observe` (dgx-2) | stack `console` (Pocket ID) |
| `jobs.yml` | `observe` (dgx-2) | stack `jobs` (Temporal) + namespace |
| `ml.yml` | `observe` (dgx-2) | stack `ml` (MLflow) + client env file |
| `backups.yml` | `observe`; all | stack `backup` + `restic_install` + `restic_prune`; `restic_install` + `restic_backup` everywhere |
| `alerting.yml` | `alerting` (Dell) | Docker at boot, stack `alerting`, `tailscale_serve` |
| `ops.yml` | `alerting` (Dell) | stack `ops` (Homepage) |
| `robot.yml` | `jetson_group`; `edge` | `ros_zenoh_router`; `ros_lidar`, `safety_governor` |
| `k3s.yml` | `k3s_init`, then `k3s_servers` one at a time, then `k3s_agents` | role `k3s` |

### Gotchas

- **Check mode can't simulate a first deploy** of a stack or of the OTel collector (folders and binaries don't exist
  yet); the role prints "would deploy" instead.
- **`compose_stack` uses `remove_orphans: true`.** Deploying a shared stack from a stale branch removes services added
  since and reverts configs. Rebase on `origin/main` first; after a merge, deploy from `main`.
- **Single-file bind mounts** keep the old inode; the role restarts the service whose folder changed. If you edit a
  file by hand on a host, restart that service yourself (and then put the change in Git).
- **DefenseClaw roles run as the target user** (`become_user`), with `XDG_RUNTIME_DIR=/run/user/<uid>` for user units.
- **`ssh -n`** when calling ssh inside a heredoc or loop, or it swallows the rest of the input.

## Cluster changes (GitOps)

1. PR touching `cluster/` or `policies/kyverno`. CI runs kubeconform and the Kyverno CLI.
2. Merge. Argo CD polls `main` every 120 s (+ up to 60 s jitter) and applies it: about 3 minutes (measured 178 s).
3. Watch: `kubectl get applications -n argocd`, `argocd --core --kube-context argocd app get <app>`.
4. Roll back: `git revert` on `main`. Don't patch the cluster by hand: selfHeal reverts it within seconds.

## Hand-run pieces (outside the repo)

The front door (`~/edge-gateway`), nginx-gateway, LiteLLM, Open WebUI, Coolify, Home Assistant, Hermes, LiveKit and the
control center are changed by hand. Back up the file first (`cp x x.bak-<what>-<date>`), change it, restart the
container or unit, check, and describe the change in a PR (or a runbook) so the next person knows.

## After a deploy

- Gatus green; no new alerts on the phone.
- `docker ps` on the host: no restarting containers.
- For k3s changes: `docker ps` on the Sparks too, and `curl http://127.0.0.1:4000/health/liveliness` on dgx-1.
