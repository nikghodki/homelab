# Open WebUI (`webui.nghodki.ai`, plan P3.7)

The chat UI for people, family included, backed by LiteLLM. In k3s since 2026-11-16 (before: a hand-run Docker
container on dgx-1, `~/open-webui`).

| | |
|---|---|
| Manifests | `cluster/apps/open-webui/` (Argo CD app `open-webui`, project `apps`) |
| Pod | `open-webui/open-webui`, 1 replica, **pinned to dgx-1** (data on its disk; LiteLLM is there), `Recreate`; root (the image's files are root's) but no capabilities and a read-only root: init container `static` copies the static folder, which Open WebUI rewrites at start, into an emptyDir |
| Image | `ghcr.io/open-webui/open-webui:v0.13.3`, by digest (allowed in `policies/kyverno/restrict-registries.yaml`) |
| Data | PVC `open-webui-data` (local-path, 20 Gi) on dgx-1: `webui.db` (SQLite: accounts, chats, settings), built-in Chroma, the embedding-model cache. Path: `kubectl get pv $(kubectl -n open-webui get pvc open-webui-data -o jsonpath='{.spec.volumeName}') -o jsonpath='{.spec.local.path}{.spec.hostPath.path}'` |
| Secrets | KSOPS Secret `open-webui` (`open-webui.enc.yaml`): `WEBUI_SECRET_KEY` (signs sessions: changing it signs everyone out), `OPENAI_API_KEY` (LiteLLM virtual key `open-webui`) |
| Models | LiteLLM `http://10.100.136.1:4000/v1` (dgx-1's cable address; LiteLLM publishes :4000) |
| Front door | `webui.nghodki.ai` → fixed ClusterIP `10.43.0.130:8080` (no cluster DNS on the door's path) |
| Network policy | in: only the edge Caddy pods; out: DNS, LiteLLM, HTTP/HTTPS to the internet (not the LAN, tailnet or cluster) |
| Resources | requests 250m / 1 Gi, limits 2 CPU / 3 Gi (it used ~800 MiB in Docker) |
| Health | Gatus `webui.nghodki.ai` (through the door), `/health` probes |

**It never starts on an empty volume.** The init container `data-present` fails until `webui.db` exists: a fresh
Open WebUI would create a new database and make its first visitor admin. If the pod sits in `Init:CrashLoopBackOff`,
the volume lost its data: restore it (below), don't delete the check.

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

Bump the tag and digest in `open-webui.yaml` (both containers), PR. `Recreate`: a short outage while the new pod
starts (it runs its database migrations on start). Take a copy of `webui.db` first (`sqlite3 webui.db ".backup
/root/webui-<date>.db"` on dgx-1, in the PV path).
