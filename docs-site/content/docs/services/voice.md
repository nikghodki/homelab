---
title: Voice (LiveKit, control center, voice page)
description: LiveKit and the RoboClaw control center on the Jetson, the voice page behind nginx-gateway on dgx-1, and the broken voice-agent LiveKit route.
---

These pieces are hand-run and only partly documented in the repo. What is known:

| Piece | Where | Details |
|---|---|---|
| LiveKit server | Jetson, user unit `livekit-server` (nikjetson) | `~/.local/bin/livekit-server --dev --key-file ~/.config/livekit/keys.yaml`; listens on 127.0.0.1:7880 and ::1:7880 only |
| LiveKit key | `~/.config/livekit/keys.yaml` (0600) | moved out of the command line (P0.8, finding F4); **rotated 2026-11-15** after it had been printed (PR #34). New key in `secrets/voice.enc.yaml` → `livekit_api_key`, `livekit_api_secret`. Old key rejected (checked) |
| RoboClaw Control Center | Jetson, user unit `control-center` | uvicorn `app.main:app` on 0.0.0.0:8200 (py310 venv); uses the LiveKit key; calls the car's `POST /stop` |
| `controlcenter.nghodki.ai` | front door → 192.168.86.211:8200 | no sign-in in Caddy (app auth unverified) |
| Voice page | dgx-1 `nginx-gateway`, server `voice-agent.nghodki.ai`: `/` → `voice-assistant.html`, `/token` → `host.docker.internal:7890` | the token service on dgx-1:7890 was not listening at check time (unverified what serves it) |
| `voice-agent.nghodki.ai` | its own Caddy site block on dgx-1, same web cert | `/rtc*` and `/twirp/*` → 100.65.137.82:7880 (dgx-1's own Tailscale IP) |
| TTS | `nginx-gateway` `/tts/` → `kokoro-tts:8880` | no `kokoro-tts` container was running at check time; P0.7 noted the missing kokoro upstream had crash-looped nginx-gateway (fixed by tolerating it) |

**Known broken:** the LiveKit route of `voice-agent.nghodki.ai` points at dgx-1:7880, but LiveKit runs on the Jetson
and listens on loopback only. `https://192.168.86.44/rtc` with Host `voice-agent.nghodki.ai` returned 502 on
2026-11-15. Fixing it means either pointing the route at the Jetson and binding LiveKit to its LAN address, or running
LiveKit on dgx-1 again; decide with whoever owns the voice agent (listed in [discrepancies](../decisions/discrepancies.md)).

Not behind Pocket ID on purpose: phone apps and LiveKit API clients would break.

Rotate the LiveKit key: generate a new pair, put it in `secrets/voice.enc.yaml`, write `keys.yaml` (0600) on the
Jetson, update the control center's settings, restart `livekit-server` and `control-center` as nikjetson, and check
that the old key is refused.
