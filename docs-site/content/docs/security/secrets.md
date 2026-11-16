---
title: SOPS and age
description: How secrets are stored (SOPS + one age key), where the key lives (including its copy in the cluster), every secrets file and key, and how to rotate.
---

All secrets are in Git, encrypted with SOPS for one age key (D16). Nothing is decrypted in CI or on GitHub.

## Rules (`.sops.yaml`)

| Path | Encrypted values | Recipient |
|---|---|---|
| `^secrets/.*\.(ya?ml\|json\|env\|ini)$` | keys matching `data`, `stringData`, `*key*`, `*token*`, `*pass*`, `*secret*`, `canary` | the fleet age key |
| `^cluster/.*\.enc\.ya?ml$` | only `data` and `stringData` (so `kind`, name and labels stay readable for Argo CD) | the fleet age key |

CI (`.github/scripts/check-sops.sh`) fails on any unencrypted file in `secrets/` (except `README.md`, `.gitkeep`), any
unencrypted `cluster/**/*.enc.yaml`, and any `kind: Secret` in `cluster/` outside an `*.enc.yaml` file.

## Where the key is

| Copy | Where | Readable by |
|---|---|---|
| Working copy | dgx-1 `~/.config/sops/age/keys.txt` (0600) | `nikghodki-dgx` |
| Offline 1 | password manager, item "homelab age key" | you |
| Offline 2 | paper, with important documents | you |
| In the cluster | Secret `argocd/sops-age` (key `keys.txt`), mounted read-only (0440, group 999) into Argo CD's repo-server at `/sops-age/keys.txt` | cluster admins, anything that can read Secrets in `argocd`, the repo-server. k3s encrypts Secrets at rest |
| Never | GitHub, CI, chat, the work laptop | — |

The cluster copy changed D16's "the key stays offline" (decision 0006). It decrypts **every** file in the repo, not only
`cluster/`. A cluster-only second key is the planned fix when workloads with their own secrets move in (P3.7).

## Files and keys

Names only; values are never written anywhere in plaintext.

| File | Keys | Used by |
|---|---|---|
| `secrets/canary.enc.yaml` | `canary` (must decrypt to `homelab-sops-ok`) | restore check |
| `secrets/pki.enc.yaml` | `pki_homelab_ca_key`, `pki_web_ca_key`, `pki_nats_key`, `pki_fleet_key`, `pki_backup_key`, `pki_web_key` | `bus.yml`, `fleet.yml`, `backups.yml`, front door |
| `secrets/observe.enc.yaml` | `grafana_admin_password`, `phoenix_admin_password`, `phoenix_secret`, `ntfy_alerts_password(_hash)`, `ntfy_alerts_token`, `ntfy_phone_password(_hash)`, `gatus_heartbeat_token`, `ntfy_sh_backup_topic_token` | `observe.yml`, `alerting.yml` |
| `secrets/console.enc.yaml` | `pocketid_encryption_key`, `pocketid_static_api_key`, `oidc_grafana_secret`, `oidc_gatus_secret`, `oidc_phoenix_secret`, `oidc_ops_secret`, `oidc_temporal_secret`, `oidc_mlflow_secret`, `oidc_argocd_secret`, `oauth2_proxy_ops_cookie_secret`, `oauth2_proxy_status_cookie_secret` | `console.yml`, the apps' playbooks, `pocketid_sync.py` |
| `secrets/bus.enc.yaml` | `nats_{admin,picoclaw,hermes,operator,sys}_password` and `_hash` | `bus.yml`, `robot.yml`, Hermes's picoclaw MCP |
| `secrets/fleet.enc.yaml` | `mosquitto_dclaw_fleet_password(_hash)`, `mosquitto_dclaw_device_1_1_1_password(_hash)`, `dclaw_fleet_api_token`, `dclaw_ota_hmac_key`, `dclaw_emergency_key`, `dclaw_audit_key_dgx1`, `dclaw_audit_key_pi`, `dclaw_device_key_1_1_1` | `fleet.yml`, `defenseclaw.yml`, `edge-connector.yml`, `collectors.yml` |
| `secrets/jobs.enc.yaml` | `postgres_password` | `jobs.yml` |
| `secrets/ml.enc.yaml` | `postgres_password`, `mlflow_api_password(_hash)`, `oauth2_proxy_mlflow_cookie_secret` | `ml.yml` |
| `secrets/k3s.enc.yaml` | `k3s_token` (full `K10<ca-hash>::server:<secret>` form) | `k3s.yml` |
| `secrets/argocd.enc.yaml` | `argocd_deploy_key`, `argocd_deploy_key_pub`, `argocd_repo_url` | Argo CD bootstrap |
| `secrets/backup.enc.yaml` | per host: `restic_password_<host>`, `rest_password_<host>`, `rest_password_hash_<host>` | `backups.yml` |
| `secrets/voice.enc.yaml` | `livekit_api_key`, `livekit_api_secret` | LiveKit and the control center on the Jetson (rotated 2026-11-15, PR #34) |
| `cluster/platform/argocd/extras/oidc.enc.yaml` | Secret `argocd-oidc` (`clientSecret`) | Argo CD via KSOPS. A copy of `oidc_argocd_secret`: rotate both together |
| `cluster/apps/_smoke/sops-canary.enc.yaml` | a canary Secret | the `smoke` app proves in-cluster decryption |

Not in SOPS yet: the LiteLLM master and salt keys (P0.14, after the DGXMM session), Hermes's `.env` files on the
Jetson, the Home Assistant long-lived token (in `/home/hermes-nikhil/.hermes/.env`).

## Use

```bash
# on dgx-1, in ~/homelab (or your worktree)
sops secrets/<name>.enc.yaml                                   # edit (opens $EDITOR, saves encrypted)
sops -d --extract '["<key>"]' secrets/<name>.enc.yaml          # read one value; don't paste it anywhere
printf '%s' "$NEW" | sops set --value-stdin secrets/<name>.enc.yaml '["<key>"]'   # set without a command-line secret
```

Playbooks load files with `community.sops.load_vars` on dgx-1 (`no_log: true`) and render them into `.env` files
(0600) or private templates (0600, owned by the container's uid).

## Restore the key (dgx-1 lost)

1. Copy the key from the password manager into `~/.config/sops/age/keys.txt` on the new machine; `chmod 600`.
2. `sops -d secrets/canary.enc.yaml` must print `canary: homelab-sops-ok`.

## Rotate the age key (yearly, or now if it may have leaked)

1. `age-keygen -o new-keys.txt`; put the new public key in both rules of `.sops.yaml`.
2. `sops updatekeys secrets/* cluster/**/*.enc.yaml` with both keys present.
3. Rotate every secret the old key could decrypt (see [Secrets rotation](../operations/secrets-rotation.md)).
4. Replace the offline copies and the cluster copy:
   `kubectl -n argocd create secret generic sops-age --from-file=keys.txt=$HOME/.config/sops/age/keys.txt --dry-run=client -o yaml | kubectl apply -f -`
   then `kubectl -n argocd rollout restart deploy/argocd-repo-server`.
5. Delete the old key.

## Gotchas

- `sops set` takes JSON values: `'"text"'` for a string. `pocketid_sync.py` and runbooks/argocd.md use `json.dumps`.
- `.gitignore` blocks `keys.txt`, `*.key`, `*.pem`, `.env*`, `*kubeconfig*`, so a decrypted file can't be committed by
  accident (which is also why the k3s role's kubeconfig task file isn't named `*kubeconfig*`).
