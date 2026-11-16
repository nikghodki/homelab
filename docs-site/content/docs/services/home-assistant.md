---
title: "Home Assistant"
description: "Home Assistant on the Jetson: container, URL, reverse-proxy settings, MCP server for Hermes, and its own login."
---

| | |
|---|---|
| Container | `homeassistant`, `ghcr.io/home-assistant/home-assistant:2026.11.1` pinned by digest (Renovate PRs), host network; stack `hosts/stacks/home-assistant`, `playbooks/home.yml` (runbooks/jetson-services.md) |
| Host / port | Jetson, 0.0.0.0:8123 |
| URL | `https://ha.nghodki.ai`: no Caddy route of its own; the front door's default route sends it to `nginx-gateway`, whose `ha.nghodki.ai` server proxies to 192.168.86.211:8123 |
| Config | `/home/nikjetson/homeassistant/config` |
| Reverse proxy | set in HA's UI (P0.16): `X-Forwarded-For` on, trusted proxies 192.168.86.44 and 100.65.137.82 |
| Sign-in | HA's own login (its phone app can't sign in through a forward-auth proxy, so it isn't behind Pocket ID) |
| MCP | HA's built-in MCP server (`http://localhost:8123/api/mcp/assist`, streamable HTTP), used by the `hermes-nikhil` profile with a long-lived token in `/home/hermes-nikhil/.hermes/.env`. Its 24 tools are pinned in `tools/homeassistant/` |
| Backups | config dir + a SQLite snapshot of `home-assistant_v2.db` are in the Jetson's restic paths |
| Health | Gatus `Home Assistant (direct)` and `ha.nghodki.ai` |
| Depends on | the Jetson; for the URL, dgx-1's front door and nginx-gateway |
| k3s target | `home`, on the Jetson (tolerates the taint) |

The tool list depends on which entities are exposed to Assist: re-export `tools/homeassistant/tools.json` after
exposing or renaming entities ([Agent cards and MCP tools](../agents/cards-and-tools.md)).

Family devices reach it over Tailscale through the front door. After any front-door or policy change, check that HA
still opens from a family device.
