---
title: Voice (retired; LiveKit and control center remain)
description: Voice and vision are retired (D26). What is left: LiveKit and the RoboClaw control center on the Jetson, a leftover voice page in nginx-gateway on dgx-1, and LiveKit key rotation.
---

**Retired for now (D26, 2026-11-15, PRs #75, #76).** `voice-agent.nghodki.ai` was removed from the front door and DNS
(edge-caddy and edge-dnsmasq on dgx-1, and the in-cluster `edge` config), and `vision-service` on the Jetson was
disabled. LiveKit and the control center stay on the Jetson for now. Bringing voice back needs a new decision.

These pieces are hand-run and only partly documented in the repo. What is left (checked 2026-11-15):

| Piece | Where | Details |
|---|---|---|
| LiveKit server | Jetson, user unit `livekit-server` (nikjetson), role `livekit` (`playbooks/home.yml`) | `/opt/livekit/1.13.5/livekit-server --config ~/.config/livekit/livekit.yaml` (no `--dev`, binary hash-locked); listens on 127.0.0.1:7880 and ::1:7880 only, so nothing off the Jetson reaches it |
| LiveKit key | in `~/.config/livekit/livekit.yaml` (0600, rendered from SOPS) | moved out of the command line (P0.8, finding F4); **rotated 2026-11-15** after it had been printed (PR #34). New key in `secrets/voice.enc.yaml` → `livekit_api_key`, `livekit_api_secret`. Old key rejected (checked) |
| RoboClaw Control Center | Jetson, user unit `control-center`, enabled and active | uvicorn `app.main:app` on 0.0.0.0:8200 (py310 venv); uses the LiveKit key; calls the car's `POST /stop` |
| `controlcenter.nghodki.ai` | front door → 192.168.86.211:8200 | no sign-in in Caddy (app auth unverified) |
| `vision-service` | Jetson, user unit (nikjetson) | **disabled and inactive** (D26) |
| `local-voice-server` | Jetson, user unit (nikjetson) | disabled (unverified what it was) |
| Voice page leftover | dgx-1 `nginx-gateway` still has a `voice-agent.nghodki.ai` server block (`/` → `voice-assistant.html`, `/token` → `host.docker.internal:7890`) in `~/voice-assistant/nginx/nginx.conf` | no route or DNS name reaches it any more |
| TTS | `nginx-gateway` `/tts/` → `kokoro-tts:8880` (under `model.nghodki.ai`) | no `kokoro-tts` container was running at check time; P0.7 noted the missing kokoro upstream had crash-looped nginx-gateway (fixed by tolerating it) |

The retired route had been broken: it sent `/rtc*` and `/twirp/*` to dgx-1:7880, while LiveKit runs on the Jetson's
loopback (502 on 2026-11-15).

Rotate the LiveKit key: generate a new pair, put it in `secrets/voice.enc.yaml`, run `playbooks/home.yml` (it
rewrites `livekit.yaml` and restarts `livekit-server`), update the control center's settings, restart
`control-center` as nikjetson, and check that the old key is refused (ListRooms check in runbooks/jetson-services.md).
