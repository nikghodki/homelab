---
title: Glossary
description: Names, abbreviations and plan IDs used across the fleet docs.
---

| Term | Meaning |
|---|---|
| A2A | Agent-to-agent protocol. Agents will call each other through LiteLLM's A2A gateway (D20, P4.10; not built yet). |
| Admin laptop | The work Mac used as the admin console. It only opens SSH tunnels; nothing is written or run on it. |
| AIBOM | AI bill of materials. Two exist: DefenseClaw's (what an agent has connected) and Cisco AIBOM (what code and images contain). |
| age | The file encryption tool SOPS uses here. One fleet age key decrypts every secret. |
| Alerting path | Gatus + ntfy on the Dell, plus Alertmanager on dgx-2. |
| Argo CD | GitOps controller in k3s. Pulls `cluster/` and `policies/kyverno` from `main`. |
| CNPG | CloudNativePG, the Postgres operator. Installed, no clusters yet. |
| compose_stack | The Ansible role that deploys every Docker Compose stack in `hosts/stacks/` to `/opt/homelab/<name>`. |
| D1–D27 | Design decisions in `docs/design.md` §6. |
| Dead man | An alert that fires when a heartbeat stops (Watchdog → Gatus; Gatus scrape → `AlertingHostDown`). |
| decision 00NN | A decision record in `decisions/`. |
| DefenseClaw | Cisco AI Defense's open-source agent security product (1.0.9). Hooks, guardrails, scanners, Fleet, Edge Connector. |
| DGXMM | DGX Model Manager: the separate project on dgx-1 that owns the GPUs and starts model engines. |
| Edge Connector | DefenseClaw's C daemon for small devices. Runs on the Pi, reports to the Fleet gateway on dgx-1. |
| edge-caddy / edge-dnsmasq | The old front door containers on dgx-1 (`~/edge-gateway`), outside the repo. Stopped on 2026-11-15, with nginx-gateway; kept a week for a rollback. |
| `edge` (namespace) | The front door in k3s (P3.3): `edge-caddy` and `edge-dns` (CoreDNS) pods on both Sparks, on the Sparks' Tailscale IPs and the kube-vip VIP. |
| Fleet (DefenseClaw) | The Fleet gateway inside dgx-1's DefenseClaw, its Mosquitto broker (8884) and API proxy (8971). |
| fleet-metrics | Small stdlib Python agent on every host (`:9109`): JSON and Prometheus host metrics. |
| Front door | Caddy in namespace `edge`, ports 80/443, for every `*.nghodki.ai` name (edge-caddy on dgx-1 before the P3.3 cutover). |
| GB10 | The DGX Spark's Grace Blackwell chip. CPU and GPU share one 121 GiB unified memory. |
| Hermes | The home agent on the Jetson. Two profiles, each as its own Linux user. |
| Homelab CA | The internal CA (no name constraint) for NATS, Fleet and backups. Fleet hosts only. |
| Web CA | The name-constrained CA for `*.nghodki.ai`, installed on phones and laptops (D25). |
| KSOPS | Kustomize plugin that decrypts SOPS files inside Argo CD's repo-server. |
| kube-vip | Floating IPs over ARP on the Sparks: 192.168.86.10 (k3s API) and 192.168.86.11 (edge). |
| LiteLLM | The model gateway (`model.nghodki.ai`), planned to be the MCP and A2A gateway too (D20). |
| MagicDNS | Tailscale's names, `<host>.tail1cb707.ts.net`. |
| MJX / MuJoCo Playground | MuJoCo on JAX; used for fast RL training on dgx-2. |
| NATS | Message bus with JetStream and MQTT, on dgx-1 (`nats.nghodki.ai`). |
| ntfy | Push notification server on the Dell; the phone subscribes to topic `fleet-alerts`. |
| Omarchy | Arch-based Linux desktop on the Dell. Inventory name `omarchy`. |
| P0.x–P6.x, PK.x | Task IDs in `docs/project-plan.md`. |
| picoclaw | The small agent on the Pi that drives the robot through an MCP server. |
| Pocket ID | Passkey-only OIDC provider at `id.nghodki.ai` (D22). |
| Safety governor | ROS 2 node on the Pi that sits between every command source and the motors. |
| SOPS | Encrypts values in YAML files in `secrets/` and `cluster/**/*.enc.yaml`. |
| Spark | An NVIDIA DGX Spark (dgx-1, dgx-2). |
| Split DNS | Tailscale setting that sends `nghodki.ai` queries to both Sparks' Tailscale IPs, where edge-dns (k3s) answers. |
| Tagged device | A Tailscale node owned by a tag instead of a person (no key expiry). |
| Zenoh | The transport under ROS 2 here (`rmw_zenoh`); router on the Jetson. |
