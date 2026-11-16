---
title: Platform
description: The two ways things are deployed today (Docker stacks by Ansible, k3s by Argo CD), and the plan to move from one to the other.
---

Two deployment systems run side by side:

| | Docker stacks (interim) | k3s (target) |
|---|---|---|
| What | Almost every service today | Argo CD, Kyverno (Enforce), CNPG operator, CoreDNS zone; P3.3 edge (in progress) |
| Source | `hosts/stacks/<name>/compose.yaml` + templates | `cluster/` and `policies/kyverno` |
| Applied by | Ansible (`hosts/playbooks/<name>.yml`), by a person, from dgx-1 | Argo CD, polling `main` every 2 min |
| Secrets | SOPS → `.env` / private templates at deploy time | SOPS → KSOPS in the repo-server |
| Where on the host | `/opt/homelab/<name>` | etcd, containerd (`/var/lib/rancher/k3s`) |

Plan P3.7 moves each Docker stack into its k3s namespace and removes the Docker copy. Until then, the Docker stacks
are the production services.

- [k3s](k3s.md): nodes, etcd, labels, taints, versions, snapshots.
- [Argo CD](argocd.md): app of apps, adding an app, sync timing, deploy key, age key, break-glass.
- [Kyverno](kyverno.md): the six policies (Enforce), exclusions, break-glass.
- [CloudNativePG](cnpg.md): operator only.
- [Docker stacks](docker-stacks.md): every stack, its host, playbook and k3s target; the `compose_stack` role.
- [Image signing](image-signing.md): `build-sign.yml`, cosign keyless, SBOMs.
