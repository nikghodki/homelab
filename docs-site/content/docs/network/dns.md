---
title: "DNS"
description: "How *.nghodki.ai resolves: edge-dnsmasq on dgx-1, split DNS on the tailnet, the CoreDNS zone inside k3s, and the AAAA NXDOMAIN quirk."
---

`nghodki.ai` is **not a registered public domain**. Only the home DNS knows it. That is why the sites use a private web
CA (D25), and why the name could in theory be registered by someone else (risk noted in D25).

## edge-dnsmasq (the authority today)

| | |
|---|---|
| Host | dgx-1, container `edge-dnsmasq` (host network, `NET_ADMIN`), image `edge-dnsmasq:local` (Alpine 3.20 + dnsmasq) |
| Config | `~/edge-gateway/dnsmasq/dnsmasq.conf` (outside the repo). Backups of earlier versions sit next to it (`dnsmasq.conf.bak-*`) |
| Listens | 192.168.86.44:53 and 100.65.137.82:53 (`bind-dynamic`, so it binds Tailscale's address when it appears) |
| Upstream | 8.8.8.8, 8.8.4.4 for everything else (`no-resolv`) |
| Zone | `local=/nghodki.ai/`: anything not listed below is NXDOMAIN |

### Records

| Name | Answers | Serves |
|---|---|---|
| `model`, `litellm-admin`, `controlcenter`, `voice-agent`, `dgxmanager`, `webui`, `coolify`, `ha` | 192.168.86.44, 100.65.137.82 | front door on dgx-1 |
| `grafana`, `status`, `ntfy`, `phoenix`, `temporal`, `mlflow`, `id`, `ops`, `ca`, `argocd` | 192.168.86.44, 100.65.137.82 | front door on dgx-1 (backends on dgx-2, the Dell, k3s) |
| `nats`, `fleet` | 192.168.86.44, 100.65.137.82 | NATS 4222/8883, Fleet 8884/8971 on dgx-1 (TLS, homelab CA) |
| `backup` | 192.168.86.36, 100.124.175.23 | restic rest-server on dgx-2 (TLS on 8000) |
| `k8s` | 192.168.86.44, 192.168.86.36, 100.65.137.82, 100.124.175.23 | k3s API on both Sparks |
| `jetson` | 192.168.86.211 | host name |
| `dgx` | 192.168.86.44 | host name |
| `pi`, `raspberrypi` | 192.168.86.34 | **stale**: the Pi is now .39 ([discrepancy](../decisions/discrepancies.md)) |
| `esp32` | 192.168.86.50 | the robot car (unverified) |

Names that do **not** exist: `hermes.nghodki.ai` (the URL in `agents/hermes/card.yaml` is a placeholder until A2A),
`dgx-2.nghodki.ai`, `omarchy.nghodki.ai`.

## Who uses it

- Tailnet devices: Tailscale split DNS for `nghodki.ai` → 100.65.137.82.
- LAN devices: only if they use 192.168.86.44 as their resolver for this zone (unverified per device).
- Containers that must reach Pocket ID don't depend on DNS: they have `extra_hosts: id.nghodki.ai:192.168.86.44`.
- k3s pods: a CoreDNS zone (below).

## The AAAA quirk

dnsmasq answers an AAAA query for a `nghodki.ai` name with **NXDOMAIN** (not an empty answer), because the name has
only A records and the zone is `local`. Go's resolver treats that NXDOMAIN as "no such host" even when the A query
succeeded. Effects:

- `kubectl` (Go) can't use `k8s.nghodki.ai`. The kubeconfig on dgx-1 points at `https://192.168.86.44:6443` instead
  (`k3s_kubeconfig_server` in `host_vars/dgx-1.yml`).
- Argo CD (Go) couldn't resolve `id.nghodki.ai`. Fixed in-cluster by the CoreDNS zone below.

Check: `dig @192.168.86.44 grafana.nghodki.ai AAAA` shows `status: NXDOMAIN`.

## CoreDNS zone in k3s

`cluster/platform/cluster-dns/coredns-custom.yaml` (Argo CD app `cluster-dns`) adds a `nghodki.ai:53` server block to
k3s's CoreDNS: cache 30 s, answer AAAA with an empty NOERROR, forward everything else to 192.168.86.44.

## Change a record

1. On dgx-1: copy the file first (`cp dnsmasq.conf dnsmasq.conf.bak-$(date +%Y%m%d%H%M%S)`), then add both lines:
   `address=/<name>.nghodki.ai/192.168.86.44` and `address=/<name>.nghodki.ai/100.65.137.82`.
2. `docker restart edge-dnsmasq`.
3. `dig +short @192.168.86.44 <name>.nghodki.ai` and the same at 100.65.137.82.
4. Add the matching Caddy route ([Front door](front-door.md)).

There is no PR for this today because the file is outside the repo. Say what you changed in the PR that needs it.

## Later

P3.3 moves DNS and the front door into k3s (CoreDNS + Caddy, 2 replicas, behind kube-vip). That work is in progress
on branch `p3.3-edge-in-cluster`: at check time Argo CD ran `edge`, `kube-vip` and `kube-state-metrics` apps from that
branch, with `edge-dns` and `edge-caddy` pods on both Sparks and a LAN VIP 192.168.86.11. It is not on `main` yet.
