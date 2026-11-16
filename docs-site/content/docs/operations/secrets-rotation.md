---
title: Secrets rotation
description: How to rotate each kind of secret in the fleet, which files and services each one touches, and what is still unrotated.
---

General pattern: generate the new value on dgx-1, write it with `sops set --value-stdin` (never on a command line),
commit the SOPS file in a PR, merge, deploy the playbooks that use it, check, and confirm the old value is refused.

| Secret | SOPS file → keys | Deploy after | Check |
|---|---|---|---|
| Fleet age key | (the key itself) | `sops updatekeys`, then every secret below, then `argocd/sops-age` | `sops -d secrets/canary.enc.yaml` |
| Web CA wildcard key | `pki` → `pki_web_key` | copy to `~/edge-gateway/conf/certs/`, restart edge-caddy | browser, Gatus cert check |
| NATS / Fleet / backup TLS keys | `pki` → `pki_nats_key`, `pki_fleet_key`, `pki_backup_key` (+ the `.crt` in `hosts/files/pki/`) | `bus.yml`, `fleet.yml`, `backups.yml` | Gatus TCP checks, client logs |
| NATS passwords | `bus` → `nats_<user>_password` + `_hash` (bcrypt `$2a$`, cost 10) | `bus.yml`; `robot.yml --limit pi` (picoclaw, operator); Hermes's `~/.picoclaw-nats-credentials` by hand | `safety-estop status`; old password refused |
| Fleet MQTT passwords | `fleet` → `mosquitto_dclaw_*_password` + `_hash` (PBKDF2 `$7$`) | `fleet.yml`, `defenseclaw.yml` (dgx-1), `edge-connector.yml` | `defenseclaw edge-connector devices` online |
| Fleet API token | `fleet` → `dclaw_fleet_api_token` | `defenseclaw.yml` (dgx-1), `collectors.yml --limit dgx-1` | Gatus `Fleet API` 401; metrics flowing |
| Fleet OTA / emergency / audit keys, device key | `fleet` → `dclaw_ota_hmac_key`, `dclaw_emergency_key`, `dclaw_audit_key_*`, `dclaw_device_key_*` | gateway and devices together; a device key changes by re-registering (`register` replaces it) | heartbeats, a policy push |
| OIDC client secrets | `console` → `oidc_<client>_secret` (regenerate in Pocket ID, then the sync script writes SOPS) | the app's playbook; for Argo CD also `cluster/platform/argocd/extras/oidc.enc.yaml` | sign in |
| Sign-in (edge-auth) | `cluster/platform/edge/edge-auth.enc.yaml` → `cookie-secret` (32 random bytes, base64url), `client-secret`; `edge_origin_token` (+ `origin-token`) | merge, restart `edge-auth` (cookie: everyone signs in again); token: restart `edge-caddy`, then `ops.yml`, `alerting.yml`, `ml.yml` (`runbooks/sign-in.md`) | sign in; `verify-edge-auth.sh` |
| Pocket ID static API key | `console` → `pocketid_static_api_key` | rebuild the KSOPS Secret `cluster/apps/pocket-id/pocket-id.enc.yaml` (byte for byte, with the trailing newline), merge, restart the pod (`runbooks/sign-in.md`) | `pocketid_sync.py --dry-run` |
| Pocket ID encryption key | `console` → `pocketid_encryption_key` | **don't rotate casually**: it encrypts Pocket ID's data (unverified whether Pocket ID supports re-keying) | — |
| ntfy users/token | `observe` → `ntfy_*_password(_hash)`, `ntfy_alerts_token` (hash with `ntfy user hash`) | `alerting.yml`, `observe.yml` (Alertmanager), phone settings | test alert |
| ntfy.sh backup topic | `observe` → `ntfy_sh_backup_topic_token` (128 random bits) | `observe.yml`; resubscribe the phone | `amtool` dead-man test |
| Gatus heartbeat token | `observe` → `gatus_heartbeat_token` | `alerting.yml` and `observe.yml` together | heartbeat endpoint green |
| Grafana / Phoenix admin | `observe` → `grafana_admin_password`, `phoenix_admin_password` | Grafana: change in the UI or with grafana-cli too (the env only sets it on first start, unverified); Phoenix: same caveat | break-glass login |
| Postgres passwords | `jobs`/`ml` → `postgres_password` | change inside Postgres first (`ALTER USER`), then the playbook | app healthy |
| MLflow job API | `ml` → `mlflow_api_password` + `_hash` (bcrypt) | `ml.yml` (rewrites the client env) | a sim job logs |
| k3s token | `k3s` → `k3s_token` | rotating it means `k3s token rotate` on a server plus every node's token file (unverified procedure; follow the k3s docs) | nodes Ready |
| Argo CD deploy key | `argocd` → `argocd_deploy_key(_pub)` | re-create `argocd/repo-homelab` | `argocd --core ... repo list` |
| restic passwords | `backup` → per host | `backups.yml` (a new repo password needs `restic key add/remove`) | a backup run |
| LiveKit key | `voice` → `livekit_api_key`, `livekit_api_secret` | by hand on the Jetson ([Voice](../services/voice.md)) | old key refused |
| LiteLLM master key | `litellm` → `litellm_master_key` | rebuild `cluster/apps/litellm/litellm.enc.yaml` (`.github/scripts/litellm-k3s-secrets.py`), merge, `kubectl -n litellm rollout restart deploy/litellm`; DGXMM's `secrets/litellm_master_key` + `docker restart dgxmm` (no `/key/regenerate`: the salt key encrypts) | `/model/info` 401 with the old key |
| LiteLLM salt key | `litellm` → `litellm_salt_key` | **two boots** with `LITELLM_MIGRATE_FROM_MASTER_KEY`, in k3s with one replica and on a test pod first (runbooks/litellm.md); `pg_dump` first | every DB route listed in `/model/info` |
| LiteLLM virtual keys | `litellm` → `picoclaw_pi_litellm_key`, `defenseclaw_jetson_judge_litellm_key`, `cisco_aibom_litellm_key` | create the new key, deploy, then `/key/delete` the old | old key 401 |
| LiteLLM database / Redis / UI | `litellm` → `litellm_db_password` (CNPG owner), `litellm_redis_password`, `litellm_ui_password` (`litellm_postgres_password` is the stopped Docker copy's) | database: `ALTER USER` in the primary, then rebuild `cluster/apps/data/litellm-db.enc.yaml` and `litellm.enc.yaml`, merge, restart the pods together; Redis and UI: rebuild the Secrets, merge, restart | readiness `db: connected` |
| Phoenix API key (LiteLLM) | `litellm` → `phoenix_api_key` (Phoenix system key `litellm-dgx-1`) | rebuild `litellm.enc.yaml`, merge, restart the pods; delete the old key in Phoenix | a trace arrives |

## Not in SOPS / not rotated yet

- Hermes `.env` files and the Home Assistant long-lived token on the Jetson.
- The LiteLLM virtual keys were reviewed (P0.17) and kept; narrowing `hermes` and `claude-code` waits for P2.0.
  Their values live only in the consumers' configs, except the keys in `secrets/litellm.enc.yaml`.
- An OpenRouter key was found in picoclaw's `.security.yml` (`custom-prefer`, unused) on 2026-11-15 and removed
  from the live file; it still has to be revoked at OpenRouter (old copies: `.security.yml.bak-*`).

## If something leaked

1. Rotate it now (table above). If the age key may have leaked, rotate the age key and then **everything**.
2. If a secret was printed in a terminal log or chat, treat it as leaked (the LiveKit key was rotated for that reason).
3. Check gitleaks/TruffleHog results in CI; never rewrite `main` history without a decision.
