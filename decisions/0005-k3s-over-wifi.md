# 0005: Build the k3s cluster over Wi-Fi now; wired Ethernet later

- Date: 2026-11-15
- Status: decided (nikghodki)

## Context

Plan P3.2 (k3s) was blocked on P0.11 (Ethernet for the Sparks). Every device's LAN link is Wi-Fi today. The Sparks
also have a direct 200 Gb/s cable to each other (`enp1s0f0np0`, 10.100.136.0/24, architecture §4.4), which does not
depend on the LAN.

## Decision

Build k3s now, before P0.11 (runbooks/k3s.md):

- **Spark to Spark** (etcd peers, API, flannel VXLAN) uses the cable, exactly as the target layout: node IPs
  10.100.136.1 / .2, `flannel-iface=enp1s0f0np0`. This part does not change when the LAN is wired.
- **The Jetson (etcd member) and Omarchy (agent)** reach the Sparks over Wi-Fi: node IPs 192.168.86.211 / .49 and
  /32 routes to 10.100.136.x via the Sparks' LAN IPs, stored on their NetworkManager Wi-Fi connection. Measured
  2026-11-15: 4–15 ms pod-to-pod over Wi-Fi, 0.4 ms Spark to Spark, MTU 1500 on every path.
- Clients (kubectl, Gatus) reach the API on the Sparks' LAN IPs (`k8s.nghodki.ai`).

## Risks

- **etcd over Wi-Fi.** One of three etcd members (the Jetson) is on Wi-Fi. etcd is sensitive to latency and to
  short outages. k3s's embedded etcd already uses lenient timers (heartbeat 500 ms, election timeout 5 s), so ordinary
  Wi-Fi jitter is fine, but a Wi-Fi drop or roam takes the Jetson out of quorum until it reconnects. The Sparks'
  own LAN is Wi-Fi too, so a router reboot cuts the Jetson off from both Sparks at once. The Sparks keep quorum
  between themselves over the cable (2 of 3).
- **A Spark can go down hard.** On 2026-11-15 both Sparks were hard-reset after GPU/unified-memory exhaustion (NVRM
  "Out of memory", then a system OOM) from model engine and NCCL test work. A model job can take a Spark out at any
  time. With one Spark down, quorum is the other Spark **plus the Jetson**: the Jetson member is what keeps the API
  writable then (tested: k3s stopped on dgx-2 for 2 minutes, dgx-1's API kept answering and accepting writes).
  If a Spark crashes while the Jetson is off Wi-Fi, etcd loses quorum and the API stops until one of them is back.
  Running containers keep running; nothing new is scheduled.
- **The Jetson's memory.** It has 7.4 GiB and about 3.4 GiB available before k3s (two Hermes profiles, Home
  Assistant, LiveKit, Zenoh, DefenseClaw). k3s + containerd take about 430 MB RSS there. The kubelet reserves
  4 GiB for the system and 768 MiB for k3s, so pods get about 2.3 GiB allocatable, and it evicts pods when available
  memory is under 300 MiB, before the OOM killer reaches the host's own services.
- **Omarchy is a laptop, but it no longer sleeps.** Since 2026-11-15 it runs the alerting path (Gatus, ntfy) and is
  kept always on (role `always_on`, PR #55: no suspend on idle or lid close; runbooks/alerting.md). If it does go
  down (power, Wi-Fi, a crash), its node goes NotReady and its pods are evicted after 5 minutes, and dgx-2's
  `AlertingHostDown` reaches the phone through ntfy.sh. Still prefer workloads that tolerate a lost node there
  (light workers; Temporal workers resume on their own).
- **Two etcd members would not be enough.** If the Jetson ever has to leave, a 2-member etcd can't survive losing
  either Spark. Don't run that way for long.

## What to monitor

- Gatus group `k3s`: the API on both Sparks (`:6443/readyz`, 401 = answering, plus the serving cert's expiry) and
  TCP to each etcd member's 2379.
- vmalert `K3sEtcdMemberDown` (one member missing for 5 min), `K3sEtcdQuorumLost`, `K3sApiDown` (vmalert/rules/k3s.yml).
- `FleetMemoryLow` and `journalctl -k | grep -i oom` on the Jetson; the Jetson's `MemoryPressure` node condition.
- Wi-Fi drops: `journalctl -u NetworkManager` on the Jetson and Omarchy; etcd "lost leader" / "slow" warnings in
  `journalctl -u k3s`.

## Moving to wired later (P0.11)

The Spark-to-Spark path stays on the cable, so nothing changes there. What changes:

1. New LAN IPs (DHCP reservations for the wired MACs) and interfaces (`enP7s7` on the Sparks). Update
   `k3s_node_external_ip`, `k3s_tls_san`, `k3s_lan_iface` and the Jetson/Omarchy `k3s_link_routes` (`via` the new
   Spark LAN IPs), plus `k8s.nghodki.ai` in edge-dnsmasq and the Gatus checks.
2. If the Jetson or Omarchy get Ethernet too: their `k3s_node_ip` and `k3s_flannel_iface` change. A node IP change
   on an etcd member means removing it from etcd and re-joining it (runbooks/k3s.md "Roll back a node", then the
   playbook). Agents just re-register.
3. Roll one node at a time, checking `kubectl get nodes` and the etcd member list between nodes, Sparks last.

## Alternatives considered

- **Wait for P0.11.** Keeps phase 3 blocked on cables for no gain on the Spark-to-Spark path, which already has its
  own link.
- **Only the two Sparks in etcd for now.** Two members can't lose either one, and a GPU OOM already took a Spark
  down once; worse than having the Jetson on Wi-Fi.
