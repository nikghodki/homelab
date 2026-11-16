---
title: Docker stacks and compose_stack
description: Every interim Docker Compose stack, its host, playbook, secrets and k3s target, and how the compose_stack role deploys them (with its gotchas).
---

Until P3.7, services run as Docker Compose stacks deployed by Ansible from dgx-1. Each stack is a folder
`hosts/stacks/<name>/` with a `compose.yaml`, plain config files and Jinja templates (`*.j2`, rendered with secrets from
SOPS). All images are pinned by digest; Renovate keeps them current.

## Stacks

| Stack | Host | Playbook | Containers | Secrets (SOPS file) | k3s target |
|---|---|---|---|---|---|
| `observe` | dgx-2 | `observe.yml` | VictoriaMetrics, vmalert, Alertmanager, Loki, Tempo, otel-defenseclaw, otel-fleet, Grafana, Phoenix | `observe`, `console` | `observe` |
| `alerting` | Dell | `alerting.yml` | Gatus 5.38.0, status-gate (Caddy 2.11.9), ntfy 2.38.0; plus `tailscale serve` | `observe`, `console` | stays on the Dell, outside the cluster |
| `ops` | Dell | `ops.yml` | Homepage 2.8.0, Caddy (docs site + Homepage gate) | `console` | stays on the Dell, outside the cluster (decision 0009) |
| `console` | dgx-2 | `console.yml` | Pocket ID 2.19.3 | `console` | `console` |
| `bus` | dgx-1 | `bus.yml` | NATS 2.15.3 | `bus`, `pki` | `bus` (3 replicas) |
| `fleet` | dgx-1 | `fleet.yml` | Mosquitto 2.1.2, Caddy 2.11.9 (host network) | `fleet`, `pki` | `security` |
| `gpu` | dgx-1, dgx-2 | `gpu.yml` | dcgm-exporter 4.8.4 | — | `observe` (DaemonSet) |
| `jobs` | dgx-2 | `jobs.yml` | Temporal 1.32.2, PostgreSQL 17, admin-tools, UI 2.58.1 | `jobs`, `console` | `jobs` |
| `ml` | dgx-2 | `ml.yml` | MLflow 3.18.0 (built locally), PostgreSQL 17, Caddy (job API + UI gate) | `ml`, `console` | `sim` |
| `backup` | dgx-2 | `backups.yml` | restic rest-server 0.14.0 | `backup`, `pki` | stays on the host |
| `litellm` | dgx-1 | `litellm.yml` | LiteLLM 1.109.1, PostgreSQL 16, Redis 7.4, DefenseClaw relay (socat) | `litellm` | `models` and `data` |
| `home-assistant` | Jetson | `home.yml` | Home Assistant 2026.11.1 (host network; config dir on the host) | — | `home` |
| `sim` | dgx-2 | none (run by hand) | isaaclab (local image on NVIDIA's + MLflow client), mujoco (local image) (profile `jobs`) | — | `sim` |

Outside the repo (hand-run): edge-gateway (`edge-caddy`, `edge-dnsmasq`; replaced for clients by `edge` in k3s at the P3.3 cutover, stopped 2026-11-15), Open WebUI (moved into k3s on 2026-11-16, namespace `open-webui`; the stopped container stays until 2026-11-23), DGXMM and engines (stay outside). nginx-gateway was stopped on 2026-11-15 (its routes are in k3s).

## The `compose_stack` role

Used by every stack playbook with `compose_stack_name` and `compose_stack_src`.

1. If `/opt/homelab/<name>/compose.yaml` doesn't exist and this is `--check`, it only prints "would deploy" (a first
   deploy can't be simulated).
2. Creates `/opt/homelab/<name>` (root, 0750) and sub-folders.
3. Copies plain files (0644) and renders `*.j2` templates without the suffix. Templates in a sub-folder listed in
   `compose_stack_private_templates` (`{service: uid}`) render 0600 owned by that uid (for example `status-gate: 65532`,
   `pocket-id: 1000`, `mosquitto: 1883`); others render 0644 root. Rendering is `no_log`.
   `compose_stack_extra_files` (`[{src, dest}]`) copies files kept elsewhere in the repo into the stack (0644; the
   first folder of `dest` names the service restarted on change), e.g. LiteLLM's guardrail plugin from `hosts/files/litellm`.
4. Writes `.env` (0600) only when `compose_stack_env` has variables (an empty `.env` failed the bus deploy, PR #16).
5. `docker_compose_v2` with `state: present`, `pull: missing`, **`remove_orphans: true`**.
6. Restarts every service whose sub-folder (named after the service) had a changed file, because single-file bind
   mounts keep the old inode (PR #12). This runs even when compose itself changed something.

Conventions: a service's config lives in a sub-folder named after the service; anything that needs a secret is a
template; nothing is published on `0.0.0.0` unless it must be (prefer `127.0.0.1:` or the host's LAN IP).

## Deploy

```bash
source ~/.venvs/ansible/bin/activate && cd ~/homelab/hosts     # or your worktree's hosts/
ansible-playbook playbooks/<stack>.yml --check --diff
ansible-playbook playbooks/<stack>.yml
ansible-playbook playbooks/<stack>.yml --check --diff          # second run: should show no changes
```

## Gotchas

- **`remove_orphans: true` removes anything not in the compose file you deploy.** If you deploy a shared stack (above
  all `observe`) from a stale branch, services that a newer PR added are removed and configs revert. **Rebase on
  `origin/main` before deploying a stack someone else also changes**, and deploy from `main` after a merge.
- Moving a service to another stack (Gatus and ntfy from `observe` to `alerting`) removes it from the old host on the
  next deploy of the old stack; its volume stays behind.
- Compose only builds a local image (MLflow, MuJoCo, Isaac Lab) when the tag is missing: bump the `image:` tag when the Dockerfile
  changes.
- Ports bound to a LAN IP fail to bind if Wi-Fi is late after a reboot; `docker compose up -d` in the stack folder
  fixes it.
- `docker` on the Dell needs `sudo`; the role uses `become`.
