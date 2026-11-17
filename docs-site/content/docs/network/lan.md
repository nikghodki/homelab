---
title: "LAN"
description: "The home LAN: Nest Wifi Pro, DHCP reservations, Wi-Fi only, and what listens on it."
---

The LAN is a Google Nest Wifi Pro mesh, 192.168.86.0/24. Every fleet device is on Wi-Fi today. The Sparks have 10 GbE
ports (`enP7s7`) that are not cabled yet (plan P0.11, "Ethernet for the Sparks (you)").

## DHCP reservations (P0.9)

Made in the Nest app with the Wi-Fi MAC addresses. After P0.11 they must be redone with the wired MACs.

| Host | Reserved IP |
|---|---|
| dgx-1 | 192.168.86.44 |
| dgx-2 | 192.168.86.36 |
| Jetson | 192.168.86.211 |
| Dell (Omarchy) | 192.168.86.49 |
| Pi | 192.168.86.39 (it used to be .34 and .39 was not reserved; F8) |

MAC addresses are not recorded here; read them on the host (`ip link`) if you need to redo a reservation.

## Why IPs are hard-coded

Many configs use LAN IPs, not names, on purpose:

- Ansible inventory (`hosts/inventory.yml`).
- Front door upstreams (`reverse_proxy 192.168.86.36:3000`).
- Gatus checks (they must work when dgx-1's DNS is down).
- `extra_hosts: id.nghodki.ai:192.168.86.11` (the front door VIP) in every container that talks to Pocket ID.
- Alertmanager → ntfy (`http://192.168.86.49:8085`).

So a changed reservation means a repo-wide search for the old address, plus `~/edge-gateway` on dgx-1.

## What is exposed on the LAN

Services that publish on all interfaces or on a LAN address (full list in [Ports](ports.md)):

| Host | Port | Service | Auth |
|---|---|---|---|
| dgx-1 | 80, 443 | front door | per route |
| dgx-1 | 4222, 8883 | NATS, MQTT (TLS) | users, deny by default |
| dgx-1 | 8884 | Fleet MQTT (TLS) | per-device users and ACLs |
| dgx-1 | 8971 | Fleet API (TLS) | bearer token |
| dgx-2 | 3000 | Grafana | Pocket ID or break-glass admin |
| dgx-2 | 6006 | Phoenix | Pocket ID or break-glass admin |
| dgx-2 | 4317–4320 | OTLP receivers | none |
| dgx-2 | 7233 | Temporal gRPC | mTLS, client certificate from the Temporal CA; roles per namespace |
| dgx-2 | 8233, 9233 | Temporal UI, metrics | UI: Pocket ID |
| dgx-2 | 4181, 5000 | MLflow (UI gate, job API) | front door token (sign-in at the door); basic auth |
| dgx-2 | 8000 | restic rest-server (TLS) | per-host htpasswd |
| Jetson | 8123 | Home Assistant | its own login |
| Jetson | 8642 | Hermes api_server (main profile) | dgx-1 only (Open WebUI), nftables `hermes_api_guard` |
| Jetson | 8200 | RoboClaw control center | (unverified) |
| Jetson | 7447 | Zenoh router | **none** (no Zenoh auth/TLS yet) |
| Dell | 8081 | Gatus via status-gate | front door token (sign-in at the door); `/health`, `/metrics`, heartbeat open |
| Dell | 8085 | ntfy | ntfy users |
| Dell | 4180, 4181 | Homepage, docs site (ops stack Caddy) | front door token (sign-in at the door) |

LiteLLM (dgx-1:4000) and Pocket ID (dgx-2:1411) left this list when they moved into k3s on 2026-11-16; their
stopped Docker copies would publish there again only in a rollback (until 2026-11-23).
| all | 9109 | fleet-metrics | none (read-only metrics) |

The design goal (§4.3) is "nothing listens on the LAN that doesn't need to". The **none** rows are known gaps.

## Gotchas

- Wi-Fi drops hit every host at once if the router reboots, including the Jetson's etcd link (decision 0005).
- A container that publishes on a specific LAN IP (`192.168.86.36:7233:7233`) can't start if that IP isn't up yet
  when Docker starts it after a reboot. Fix: `sudo docker compose --project-directory /opt/homelab/<stack> up -d`
  once Wi-Fi is up (see [Troubleshooting](../operations/troubleshooting.md)).
