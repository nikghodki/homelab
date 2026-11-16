---
title: Phoenix
description: LLM and agent tracing on dgx-2 (Arize Phoenix), behind Pocket ID; nothing sends traces to it yet.
---

| | |
|---|---|
| Purpose | LLM and agent traces (D11), one container, OpenTelemetry-native |
| Version | `arizephoenix/phoenix:version-21.1.0` (digest-pinned) |
| Host | dgx-2, part of the `observe` stack |
| Port | 0.0.0.0:6006 (UI and OTLP HTTP at `/v1/traces`) |
| URL | `https://phoenix.nghodki.ai` |
| Sign-in | `PHOENIX_ENABLE_AUTH=true`; Pocket ID client `phoenix` (PKCE, scope `groups`, `admins` → ADMIN, else VIEWER, only `admins` allowed); default admin as break-glass |
| Secrets | `secrets/observe.enc.yaml` → `phoenix_secret`, `phoenix_admin_password`; `secrets/console.enc.yaml` → `oidc_phoenix_secret` |
| Data | volume `observe_phoenix-data` (`PHOENIX_WORKING_DIR=/data`) |
| Health | Gatus `Phoenix` (`http://192.168.86.36:6006/healthz`) |
| AIBOM | its image is scanned nightly on dgx-2 |

Status: P2.6 is partial. Phoenix is up; LiteLLM → Phoenix is connected in the P0.14 window after the DGXMM session.
project-quarry (decision 0003) could later run detection rules over exported traces.

Gotcha: without `PHOENIX_OAUTH2_POCKETID_SCOPES: groups`, Pocket ID sends no groups claim and Phoenix answers
"authentication failed" (PR #36).
