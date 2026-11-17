# Open WebUI, "Ask Me" (`webui.nghodki.ai`, plan P3.7)

The chat UI for people, family included, backed by LiteLLM; called **Ask Me** since 2026-11-17. Two ways to answer:
**direct** (the default model through LiteLLM, for everyone) and the **Hermes agent** (admins only). In k3s since 2026-11-16 (before: a hand-run Docker
container on dgx-1, `~/open-webui`).

| | |
|---|---|
| Manifests | `cluster/apps/open-webui/` (Argo CD app `open-webui`, project `apps`) |
| Pod | `open-webui/open-webui`, 1 replica, **pinned to dgx-1** (data on its disk), `Recreate`; root (the image's files are root's) but no capabilities and a read-only root: init container `static` copies the static folder, which Open WebUI rewrites at start, into an emptyDir |
| Image | `ghcr.io/nikghodki/open-webui:v0.13.3-askme.1` by digest: upstream v0.13.3 plus the Ask Me patch ([below](#ask-me-overlay)), signed by build-sign |
| Data | PVC `open-webui-data` (local-path, 20 Gi) on dgx-1: `webui.db` (SQLite: accounts, chats, settings), built-in Chroma, the embedding-model cache. Path: `kubectl get pv $(kubectl -n open-webui get pvc open-webui-data -o jsonpath='{.spec.volumeName}') -o jsonpath='{.spec.local.path}{.spec.hostPath.path}'` |
| Secrets | KSOPS Secret `open-webui` (`open-webui.enc.yaml`): `WEBUI_SECRET_KEY` (signs sessions: changing it signs everyone out), `OPENAI_API_KEY` (LiteLLM virtual key `open-webui`), `OWUI_ADMIN_API_KEY` (the admin account's API key, used only by the config Job), `HERMES_API_KEY` (copy of `hermes_api_key_nikjetson` in `secrets/hermes.enc.yaml`) |
| Models | connection 0: LiteLLM in k3s, `http://10.43.0.150:4000/v1` (fixed ClusterIP); connection 1: Hermes on the Jetson, `http://192.168.86.211:8642/v1`. Both **in Open WebUI's database**, set from Git by the config Job ([below](#config-from-git)) |
| Settings from Git | `config/settings.yaml` + `functions/` → ConfigMap → PostSync Job `open-webui-config` ([below](#config-from-git)) |
| Front door | `webui.nghodki.ai` → fixed ClusterIP `10.43.0.130:8080` (no cluster DNS on the door's path) |
| Network policy | in: the edge Caddy pods and the config Job; out: DNS, the LiteLLM pods (:4000), Hermes `192.168.86.211:8642`, HTTP/HTTPS to the internet (not the rest of the LAN, the tailnet or the cluster). The Job may only reach the Open WebUI pod |
| Resources | requests 250m / 1 Gi, limits 2 CPU / 3 Gi (it used ~800 MiB in Docker) |
| Health | Gatus `webui.nghodki.ai` (through the door), `/health` probes |

**It never starts on an empty volume.** The init container `data-present` fails until `webui.db` exists: a fresh
Open WebUI would create a new database and make its first visitor admin. If the pod sits in `Init:CrashLoopBackOff`,
the volume lost its data: restore it (below), don't delete the check.

## Ask Me overlay

The UI is called **Ask Me**. Open WebUI appends " (Open WebUI)" to any `WEBUI_NAME` other than its default
(`backend/open_webui/env.py`), so the pod runs a small overlay of the upstream image, `ghcr.io/nikghodki/open-webui`:

| | |
|---|---|
| Source | `cluster/apps/open-webui/image/`: `Dockerfile` (FROM the upstream image by digest), `patch_branding.py` (tests in `tests/`, run in CI), `LICENSE.open-webui` (copied to `/app/LICENSE.open-webui`) |
| Patch | drops the two lines that add the suffix (the licence comment above them stays) and sets the static `<title>` (shown until the app sets it from `WEBUI_NAME`). Each edit must match exactly once, or the build fails with "the Ask Me patch no longer applies: ...". Logo and favicon stay upstream's |
| Tag | `<upstream tag>-askme.<revision>`, e.g. `v0.13.3-askme.1` (`# askme-revision:` in the Dockerfile; bump it when the patch changes on the same upstream version, reset it to 1 on a new one) |
| Build | `build-sign.yml` on main (signed, SBOM attested; Kyverno's `verify-images` admits it), linux/arm64 only; the manifest pins the digest |
| Upgrades | Renovate opens PRs for the FROM line (rule in `renovate.json`). The PR's "Open WebUI overlay builds on its pinned base" step builds the overlay, so a patch that no longer applies fails the PR. After merge: the digest from the build-sign run summary goes into `open-webui.yaml` (all three containers) and `config-job.yaml`, as in [Upgrade](#upgrade) |
| Package | `ghcr.io/nikghodki/open-webui` must be **public** (nodes and Kyverno pull without a credential; runbooks/build-sign.md, "Visibility"). It holds nothing private: upstream's image plus the patch |

**Licence.** The Open WebUI License is BSD-3 plus a branding clause: changing or removing the "Open WebUI" branding
is allowed only for deployments with **at most 50 end users in any rolling 30 days** (or with written permission or an
enterprise licence). This household deployment qualifies; the rebrand relies on that clause. Copyright notices in
the source are kept and the licence ships in the image. The image is public, so anyone who runs or redistributes this
rebranded build is bound by the same clause (more than 50 users: the branding must stay).
## Config from Git

Open WebUI keeps nearly all settings in its database, and **database values win over env vars** (a stale
`OPENAI_API_BASE_URL` in the database once broke every chat). So the settings that matter are in Git and applied
through Open WebUI's admin API, then read back:

| | |
|---|---|
| What | `cluster/apps/open-webui/config/settings.yaml`: the two connections (URLs; keys named by env var), model names, access and capabilities, the `admins` group, the default model and model order, the API-key policy; `functions/tps_meter.py` (the TPS meter) |
| How | kustomize puts them in a hashed ConfigMap; after every Argo CD sync the **PostSync Job `open-webui-config`** runs `config/apply_config.py`: wait for `/health`, check the key is an admin's, then per item read the current value and write only what differs; models (with their access) before connections. Finally it reads the **effective** values back (`/openai/config`, `/api/models`, the functions, `/api/v1/configs/models`) and fails if anything differs from Git. Keys are never logged: "key matches LITELLM_API_KEY" / "DIFFERS" |
| Auth | `OWUI_ADMIN_API_KEY`, an API key of the admin account (Open WebUI keeps keys in `api_key`). API keys are on, **with endpoint restrictions**: a key may only call the paths in `settings.yaml` (no `/api/v1/chats`, files, knowledge or memories: it can't read anyone's chats). Family accounts can't create keys (`features.api_keys` off) |
| Logs | `kubectl -n open-webui logs job/open-webui-config` (kept until the next sync) |
| Run again | without a Git change: `kubectl -n open-webui create job --from=job/open-webui-config owui-config-manual` (delete it after); or check only: `kubectl -n open-webui exec deploy/open-webui -c open-webui -- env OWUI_ADMIN_API_KEY=… python3 …/apply_config.py --verify-only` |

A change made in the admin UI to one of these settings is overwritten by the next sync. Settings not in
`settings.yaml` stay UI-managed.

**Bootstrap (done 2026-11-17, once).** The Job needs an admin API key before it can set anything, and creating one
needs an admin session (a passkey). It was inserted directly, like the connection fix below: with a `webui.db` copy
taken, one row in `api_key` for the admin account with the value of `OWUI_ADMIN_API_KEY`, and `auth.enable_api_keys`,
`auth.api_key.endpoint_restrictions`, `auth.api_key.allowed_endpoints` set to the values in `settings.yaml`. To rotate
it: new value in `open-webui.enc.yaml`, update that row (`update api_key set key=?, updated_at=? where user_id=<admin>`),
merge; the next Job run proves it.

## Routing: direct or Hermes

The model picker shows:

| Model (id) | Goes to | Who sees it |
|---|---|---|
| **Ask Me — direct (qwen3.8-27b)** (`qwen3.8-27b`) | connection 0, LiteLLM → DGXMM's on-demand `qwen3.8-27b` (decision 0012). The default for new chats | everyone (access `public`) |
| **Ask Me — Hermes agent** (`hermes.hermes-agent`) | connection 1 (prefix `hermes`, only the model `hermes-agent`), Hermes' main profile on the Jetson: an agent run with Hermes' tools (terminal, Home Assistant, …), streamed back | the `admins` group only |
| other LiteLLM models (coder, twil, …) | connection 0 | admins only (models without an entry are admin-only in Open WebUI) |

Background tasks (titles, tags, follow-ups) always use `qwen3.8-27b` (`task.model.external`), never Hermes.

## Hermes

| | |
|---|---|
| API | Hermes' `api_server` platform: **OpenAI-compatible**, `GET /v1/models` (one model, `hermes-agent`), `POST /v1/chat/completions` with **SSE streaming** (`reasoning_content` and `content` deltas; the usage block rides on the `finish_reason` chunk), plus `/v1/responses`, `/v1/runs`, `/api/sessions`, `/health`. Bearer `API_SERVER_KEY`; no key or a wrong one: 401 |
| Profiles | one API server per profile: **:8642 = main profile `nikjetson`** (binds 0.0.0.0), **:8643 = `hermes-nikhil`** (binds 100.78.145.123 only). `gateway.multiplex_profiles` is off, so `/p/<profile>/` isn't served. Open WebUI uses only :8642 |
| Keys | `secrets/hermes.enc.yaml`: `hermes_api_key_nikjetson`, `hermes_api_key_hermes_nikhil`. On the Jetson in `~/.hermes/api_server.env` (`API_SERVER_KEY`, and `HERMES_API_KEY` with the same value) of each account, mode 0600, read by the unit's `EnvironmentFile`; nikjetson's rollback copy `~/hermes-homes/nikhil-ghodki/api_server.env` has hermes-nikhil's |
| Who may call it | the Jetson accepts :8642 only from loopback and dgx-1 (`192.168.86.44`; the pod's traffic is masqueraded to it): nftables table `inet hermes_api_guard`, role `hermes_api_guard`, `playbooks/hermes-api-guard.yml`. In k3s, the Open WebUI pod is the only one whose egress policy allows it. Other processes on dgx-1 still need the key |
| Safety | Hermes has home and robot tools. The model is admins-only (access grant to the `admins` group; family accounts don't see it and get "Model not found" if they name it); motion from the hermes-nikhil profile goes through picoclaw and the governor (runbooks/robot-safety.md). **Test only with harmless prompts** ("what time is it?", "list your tools without running any") and check the Pi afterwards: `journalctl -t robot-motion-bridge --since …` and `journalctl -t safety-governor --since …` show no new command |
| TPS | for Hermes the meter measures the whole agent run (every model call and tool step between the first and the last token) and is prefixed "Agent run:" |

**Rotating a Hermes key** (done 2026-11-17 for both profiles: the main profile's old key had leaked in a deleted
`~/voice-assistant/agent.py`; old key → 401 afterwards). Nothing else uses these keys (checked by value on dgx-1,
dgx-2, the Jetson and the Pi):

1. New value into SOPS: `openssl rand -hex 32 | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()), end="")' | sops set --value-stdin secrets/hermes.enc.yaml '["hermes_api_key_nikjetson"]'`.
2. On the Jetson, replace the `API_SERVER_KEY=` and `HERMES_API_KEY=` lines of `~/.hermes/api_server.env` (value on
   stdin, file stays 0600), then `systemctl --user restart hermes-gateway` (about 12 s without the API; for
   hermes-nikhil `sudo -u hermes-nikhil env XDG_RUNTIME_DIR=/run/user/$(id -u hermes-nikhil) systemctl --user restart hermes-gateway`).
   A restart loads Hermes' plugins again: any plugin DefenseClaw quarantined since the last start is gone afterwards
   (runbooks/hermes-profiles.md).
3. Main profile: copy it into `open-webui.enc.yaml` (`HERMES_API_KEY`), PR, merge; the Job sets the connection.
4. Check: `curl -H "Authorization: Bearer <old>" http://192.168.86.211:8642/v1/models` → 401, the new key → 200.

## TPS meter

A global **filter function** (`functions/tps_meter.py`, tests in `functions/tests`, run in CI), on every model. While
a reply streams the status line under the model name shows `≈ 42.0 tok/s · 128 tokens so far` (every 0.5 s, every 2 s
after 60 updates: each status is also saved in the chat). When it ends: `38.2 tok/s · 512 output tokens · first token
0.41 s · 13.8 s total`.

- Exact counts come from the provider's `usage` in the last chunk: the models' **usage** capability is on in
  `settings.yaml`, so Open WebUI sends `stream_options.include_usage` (LiteLLM passes it to vLLM; Hermes always sends
  usage). Without a usage block the numbers are an estimate from the streamed text (~4 characters a token, at least
  one per chunk) and every figure carries "≈".
- tok/s = output tokens (reasoning included) / time from the first to the last token; "first token" is measured from
  when Open WebUI starts handling the request (a cold model start shows up there: ~4.5 min).
- Valves (admin UI → Functions → TPS meter): `update_interval`, `slow_after_updates`, `slow_update_interval`,
  `pipeline_model_prefixes` (`hermes.`), `pipeline_label`. Valves are stored in the database, not in Git.

## Model connection

Open WebUI keeps its OpenAI connection in its database (config key `openai.api_base_urls`, with the key in
`openai.api_keys`); the `OPENAI_API_BASE_URL` env var is only read on the very first start. So the move into k3s left
it on `http://litellm-proxy:4000/v1` (the Docker name, unresolvable in a pod: no models) until it was set to the
cable address on 2026-11-16 and to LiteLLM's ClusterIP after LiteLLM's move. Change it in the admin UI (Settings →
Connections), or without a session (it reads the config from the database on every request, so no restart):

```bash
kubectl -n open-webui exec -i deploy/open-webui -c open-webui -- python3 - http://10.43.0.150:4000/v1 <<'PY'
import sqlite3, json, sys, time
c = sqlite3.connect("/app/backend/data/webui.db", timeout=30)
c.execute("update config set value=?, updated_at=? where key='openai.api_base_urls'", (json.dumps([sys.argv[1]]), int(time.time())))
c.commit(); print(c.execute("select value from config where key='openai.api_base_urls'").fetchone()[0])
PY
```

Take a `webui.db` copy first (below). Keep the env var the same, for a fresh install.

## Move or restore the data

Open WebUI must be stopped while its files are copied (SQLite). As root on dgx-1:

```bash
export KUBECONFIG=~/.kube/config
PV=$(kubectl -n open-webui get pvc open-webui-data -o jsonpath='{.spec.volumeName}')
DST=$(kubectl get pv $PV -o jsonpath='{.spec.local.path}{.spec.hostPath.path}')    # local-path: a hostPath on dgx-1
SRC=/var/lib/docker/volumes/open-webui_open-webui-data/_data                       # or a restic restore
kubectl -n open-webui scale deploy/open-webui --replicas=0   # Argo CD's selfHeal sets it back to 1 within minutes:
                                                             # be quick, or pause auto-sync (runbooks/argocd.md)
sudo rsync -aHAX --delete "$SRC/" "$DST/"
kubectl -n open-webui delete pod -l app.kubernetes.io/name=open-webui   # or let selfHeal scale it back up
kubectl -n open-webui rollout status deploy/open-webui --timeout=5m
```

## The move from Docker (2026-11-16)

1. PR "Open WebUI in k3s": the app (pod blocked by `data-present`), the registry in Kyverno's allowlist, and the
   Caddy route with **two upstreams, `lb_policy first`**: the pod, then the Docker copy on `100.65.137.82:3100`. Active
   health checks (`/health` every 5 s) send traffic to the pod as soon as it is up, to Docker until then.
2. Cutover (the only downtime): `docker stop open-webui` (data now consistent), rsync the volume into the PV, delete
   the blocked pod so the init container runs again at once, wait for `Ready`. Caddy switches by itself.
3. Verify: Gatus `webui.nghodki.ai`, sign-in with an existing account, a chat that streams a reply, the family
   check from a phone.
4. The Docker copy stays **stopped, not removed, until 2026-11-23** (rollback: `docker start open-webui`; Caddy
   falls back to it while the pod is down). Then PR "Open WebUI: drop the Docker fallback" removes the second
   upstream, and the container, `~/open-webui` and the volume `open-webui_open-webui-data` can be deleted.

## Rollback

While the Docker copy exists: scale the pod to 0 (pause Argo CD auto-sync for `open-webui` first), copy the PV back
into the Docker volume if anything was written since the move, `docker start open-webui`. Caddy's `first` policy
uses it as soon as the pod's health check fails. Revert the PR to remove the app.

## Upgrade

Renovate bumps the overlay's FROM line ([Ask Me overlay](#ask-me-overlay)); after that PR is merged and build-sign has
pushed the new overlay, put its tag and digest in `open-webui.yaml` (all three containers) and in `config-job.yaml`, PR. `Recreate`: a short outage while the new pod
starts (it runs its database migrations on start). Take a copy of `webui.db` first (`sqlite3 webui.db ".backup
/root/webui-<date>.db"` on dgx-1, in the PV path).
