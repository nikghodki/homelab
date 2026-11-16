---
title: "DNS"
description: "How *.nghodki.ai resolves: edge-dns in k3s since the P3.3 cutover (tailnet and LAN views), split DNS on the tailnet, the k3s CoreDNS forward, edge-dnsmasq kept on dgx-1 for rollback, and the AAAA quirk."
---

`nghodki.ai` is **not a registered public domain**. Only the home DNS knows it. That is why the sites use a private web
CA (D25), and why the name could in theory be registered by someone else (risk noted in D25).

Since the P3.3 cutover (PR #79, 2026-11-15; decision 0007, runbook `runbooks/edge.md`) the authority is **edge-dns in
k3s**. edge-dnsmasq on dgx-1 still runs, for the rollback.

## edge-dns (in k3s, the authority)

| | |
|---|---|
| Pods | `edge/edge-dns` (CoreDNS, 2 replicas, one per Spark), Argo CD app `edge` |
| Names | one list, `cluster/platform/edge/names.txt`; `.github/scripts/edge-zone.py generate` writes the zones (`coredns/lan.db`, `tailnet-dgx-1.db`, `tailnet-dgx-2.db`); CI runs `edge-zone.py check` |
| Tailnet view | both Sparks' Tailscale IPs :53 (Service `edge-dns-tailnet`, `externalIPs` 100.65.137.82 and 100.124.175.23). Each replica answers with **its own Spark's** Tailscale IP, TTL 30 s, so an answer never names a dead Spark. Non-`nghodki.ai` queries are REFUSED |
| LAN view | the edge VIP 192.168.86.11:53 (kube-vip, Service `edge-dns-lan`, ClusterIP 10.43.0.53); other names are forwarded to the router 192.168.86.1. Nothing uses LAN DNS today (the router doesn't forward `nghodki.ai`) |
| Checks | Gatus group `edge` (DNS on the VIP and on both Tailscale IPs, over TCP); vmalert `front-door` rules |

### Names (`names.txt`)

| Target | Names | LAN answer | Tailnet answer |
|---|---|---|---|
| `edge` (the front door, Caddy) | `model`, `litellm-admin`, `controlcenter`, `dgxmanager`, `webui`, `ha`, `grafana`, `status`, `ntfy`, `ca`, `id`, `ops`, `phoenix`, `temporal`, `mlflow`, `argocd`; `docs` (added by the docs-site PR) | 192.168.86.11 | the answering Spark's Tailscale IP |
| `dgx-1` | `nats`, `fleet` (NATS 4222/8883, Fleet 8884/8971, TLS with the homelab CA) | 192.168.86.44 | 100.65.137.82 + LAN IP |
| `dgx-2` | `backup` (restic rest-server, TLS on 8000) | 192.168.86.36 | 100.124.175.23 + LAN IP |
| `api` | `k8s` | the API VIP 192.168.86.10 | the answering Spark's Tailscale IP |
| fixed address | `jetson` 192.168.86.211, `dgx` 192.168.86.44, `esp32` 192.168.86.50 (the robot car, unverified) | same | same |
| fixed address | `pi`, `raspberrypi` 192.168.86.34 | **stale**: the Pi is now .39 ([discrepancy](../decisions/discrepancies.md)) | same |

`voice-agent.nghodki.ai` was removed on 2026-11-15 (D26, voice retired; #75, #76).

Names that do **not** exist: `hermes.nghodki.ai` (the URL in `agents/hermes/card.yaml` is a placeholder until A2A),
`dgx-2.nghodki.ai`, `omarchy.nghodki.ai`.

## Who uses it

- Tailnet devices (every client): Tailscale split DNS for `nghodki.ai` (and a separate `model.nghodki.ai` entry) →
  100.65.137.82 and 100.124.175.23 (`tailscale dns status` on dgx-1, 2026-11-15, after the cutover). On dgx-1's
  Tailscale IP, kube-proxy DNATs :53 to edge-dns ahead of dnsmasq.
- LAN devices: only if they use the VIP (or 192.168.86.44) as their resolver for this zone (unverified per device).
  Don't point the router's DNS at the VIP: edge-dns forwards to the router (a loop; `loop` stops CoreDNS).
- Containers that must reach Pocket ID don't depend on DNS: they have `extra_hosts: id.nghodki.ai:192.168.86.44`
  (edge-caddy on dgx-1, which still serves every route on dgx-1's LAN IP).
- k3s pods: through k3s's CoreDNS (below).

## CoreDNS forward in k3s

`cluster/platform/cluster-dns/coredns-custom.yaml` (Argo CD app `cluster-dns`) adds a `nghodki.ai:53` server block to
k3s's CoreDNS: cache 30 s, AAAA answered with an empty NOERROR, everything else forwarded to edge-dns at **10.43.0.53**
(the LAN view: front-door names → the VIP). Before the cutover it forwarded to edge-dnsmasq at 192.168.86.44.

## edge-dnsmasq (old door, rollback)

| | |
|---|---|
| Host | dgx-1, container `edge-dnsmasq` (host network, `NET_ADMIN`), image `edge-dnsmasq:local` (Alpine 3.20 + dnsmasq) |
| Config | `~/edge-gateway/dnsmasq/dnsmasq.conf` (outside the repo; backups `dnsmasq.conf.bak-*` next to it). Same records as `names.txt` for an `edge` name: 192.168.86.44 and 100.65.137.82 |
| Listens | 192.168.86.44:53 and 100.65.137.82:53 (`bind-dynamic`). Since the cutover, queries to 100.65.137.82:53 are DNATed to the cluster first, so in practice only 192.168.86.44:53 reaches it |
| Upstream | 8.8.8.8, 8.8.4.4 (`no-resolv`) |

Rollback (`runbooks/edge.md`, "Cutover" → "Rollback"): reverting #79, or dropping 100.65.137.82 from the two tailnet
Services, hands dgx-1's Tailscale IP back to dnsmasq and edge-caddy, which never stopped listening.

## The AAAA quirk

dnsmasq answers an AAAA query for a `nghodki.ai` name with **NXDOMAIN** (not an empty answer), because the name has
only A records and the zone is `local`. Go's resolver treats that NXDOMAIN as "no such host" even when the A query
succeeded. edge-dns is authoritative and answers AAAA with **NOERROR and no answer**, so clients that use the cluster
are fine since the cutover. Left over:

- The kubeconfig on dgx-1 still points at `https://192.168.86.44:6443` (`k3s_kubeconfig_server` in
  `host_vars/dgx-1.yml`); `k8s.nghodki.ai` can now be used instead (unverified with kubectl).
- Check: `dig @100.65.137.82 grafana.nghodki.ai AAAA` → `NOERROR` (cluster); `dig @192.168.86.44 ... AAAA` →
  `NXDOMAIN` (dnsmasq).

## Change a record

Since the cutover, in Git only (`runbooks/edge.md`, "Add or change a route"):

1. Add `<name>  edge` (or a host target, see the file's header) to `cluster/platform/edge/names.txt`, run
   `.github/scripts/edge-zone.py generate`, PR, merge. Argo CD rolls edge-dns within ~3 minutes.
2. Add the Caddy route ([Front door](front-door.md#add-a-route)).
3. Check: `dig +short @100.65.137.82 <name>.nghodki.ai`, the same at 100.124.175.23 and at the VIP 192.168.86.11.
4. To keep the rollback complete (and for a route behind nginx-gateway), also add the `address=` lines from
   `.github/scripts/edge-zone.py dnsmasq` to `~/edge-gateway/dnsmasq/dnsmasq.conf` on dgx-1 (back it up first),
   `docker restart edge-dnsmasq`, and check with `edge-zone.py diff-dnsmasq ~/edge-gateway/dnsmasq/dnsmasq.conf`.
