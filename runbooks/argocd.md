# Argo CD (plan P3.4)

Argo CD pulls `cluster/` (and `policies/kyverno`) from `git@github.com:nikghodki/homelab.git`, `main`, with a
read-only deploy key, and decrypts SOPS files with KSOPS. Nothing pushes into the cluster (design D15). Layout:
[cluster/README.md](../cluster/README.md). Why this shape: [decision 0006](../decisions/0006-gitops-platform.md).

| | |
|---|---|
| Version | Argo CD **v3.6.1**, Helm chart `argo-cd` **10.18.0** (`cluster/bootstrap/apps/argocd.yaml`), KSOPS **v4.5.1** (digest-pinned init container) |
| Values | `cluster/platform/argocd/values.yaml`; extras (OIDC secret, host Services, NetworkPolicies) in `cluster/platform/argocd/extras/` |
| Runs | namespace `argocd`, Sparks only (`nghodki.ai/role=gpu`), one replica each: application controller, repo-server, server, redis. No Dex, notifications, ApplicationSet controller (0 replicas) or commit server |
| UI | `https://argocd.nghodki.ai`: edge-caddy on dgx-1 → fixed ClusterIP `10.43.0.100:80` (server in insecure mode; TLS ends at Caddy) |
| Sign-in | Pocket ID, client `argocd` (PKCE S256, `identity/pocket-id.yaml`); group `admins` → `role:admin`, everyone else nothing. Built-in `admin` is **off** |
| CLI | on dgx-1: `argocd --core --kube-context argocd app list` (talks to the Kubernetes API with the admin kubeconfig; no Argo CD login) |
| Polling | every 2 min plus up to 1 min jitter (`timeout.reconciliation: 120s`); GitHub can't call in |
| Metrics | controller `10.43.0.101:8082`, server `10.43.0.100:8083`, repo-server `10.43.0.102:8084`, scraped by VictoriaMetrics on dgx-2. Dashboard: Grafana → Cluster → Argo CD |
| Alerts | `ArgoCDAppOutOfSync`, `ArgoCDAppNotHealthy` (15 min), `ArgoCDMetricsDown` (10 min): `hosts/stacks/observe/vmalert/rules/gitops.yml` |

The `argocd` kube context on dgx-1 is the admin context with namespace `argocd`
(`kubectl config set-context argocd --cluster=homelab --user=homelab --namespace=argocd`).

## Apps

`root` (`cluster/bootstrap/apps/`, manages itself) creates every other Application and the AppProjects:

| App | Project | Source |
|---|---|---|
| `root` | default | `cluster/bootstrap/apps` |
| `argocd` | default | chart argo-cd + `cluster/platform/argocd/extras` |
| `kyverno` | platform | chart kyverno + `cluster/platform/kyverno/extras` |
| `kyverno-policies` | platform | `policies/kyverno` |
| `cnpg-operator` | platform | chart cloudnative-pg |
| `cluster-dns` | platform | `cluster/platform/cluster-dns` (CoreDNS zone for `*.nghodki.ai`) |
| `kube-vip` | platform | `cluster/platform/kube-vip` (API VIP 192.168.86.10, edge VIP 192.168.86.11; runbooks/edge.md) |
| `edge` | platform | `cluster/platform/edge` (the front door: CoreDNS + Caddy; runbooks/edge.md) |
| `kube-state-metrics` | platform | `cluster/platform/kube-state-metrics` (readiness metrics for vmalert) |
| `smoke` | apps | `cluster/apps/_smoke` (SOPS canary) |

All have automated sync with prune and selfHeal, and retries. Only `smoke` has the resources finalizer: deleting
the `argocd`, `kyverno` or `cnpg-operator` Application leaves the components (and their CRDs, so no Postgres
cluster disappears with it).

## Add an app

See [cluster/apps/README.md](../cluster/apps/README.md): a folder in `cluster/apps/<name>/` and an Application in
`cluster/bootstrap/apps/<name>.yaml`. Merge; `root` creates it within about 3 minutes. A platform component (cluster
scope, a Helm chart) goes in `cluster/platform/<name>/` with project `platform` instead. Remove an app by deleting
both; `root` prunes the Application.

**Measured (2026-11-15):** a label change was applied with no manual step **89 s** after a push (to the PR
branch, while bootstrapping) and **178 s** after the merge of PR #58 to `main`. Argo CD polls every 120 s plus up to
60 s of jitter, so expect up to about 3 minutes.

Roll back a bad deploy: revert the commit on `main`. Don't fix things by hand in the cluster: selfHeal puts Git's
version back within seconds.

## Status

```bash
export KUBECONFIG=~/.kube/config
kubectl get applications -n argocd                     # SYNC STATUS / HEALTH STATUS
argocd --core --kube-context argocd app get <app>      # resources and the last sync result
argocd --core --kube-context argocd app diff <app>
kubectl -n argocd get app <app> -o jsonpath='{.status.conditions}'   # ComparisonError etc.
```

## Bootstrap (empty cluster; done once on 2026-11-15)

On dgx-1, from a checkout of `main`, with `helm` and `sops` in `~/.local/bin`:

```bash
export KUBECONFIG=~/.kube/config PATH=$HOME/.local/bin:$PATH
kubectl create namespace argocd
# 1. The age key, straight from the file (never echoed): KSOPS in the repo-server decrypts with it.
kubectl -n argocd create secret generic sops-age --from-file=keys.txt=$HOME/.config/sops/age/keys.txt
# 2. The repo credential, from SOPS through a pipe.
python3 - <<'PY' | kubectl apply -f -
import json, subprocess
d = json.loads(subprocess.run(["sops", "-d", "--output-type", "json", "secrets/argocd.enc.yaml"],
                              capture_output=True, text=True, check=True).stdout)
print(json.dumps({"apiVersion": "v1", "kind": "Secret",
  "metadata": {"name": "repo-homelab", "namespace": "argocd", "labels": {"argocd.argoproj.io/secret-type": "repository"}},
  "type": "Opaque",
  "stringData": {"type": "git", "name": "homelab", "url": d["argocd_repo_url"], "sshPrivateKey": d["argocd_deploy_key"]}}))
PY
# 3. Argo CD itself, with the same values Argo CD will use for itself.
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd --version 10.18.0 -n argocd -f cluster/platform/argocd/values.yaml --wait
# 4. Hand over to Git.
kubectl apply -f cluster/bootstrap/apps/root.yaml
kubectl get applications -n argocd -w                 # all Synced/Healthy in a few minutes
# 5. Argo CD now owns the release: drop Helm's record so nobody `helm upgrade`s it by mistake.
kubectl -n argocd delete secret -l owner=helm,name=argocd
```

`sops-age` and `repo-homelab` are the only things in the cluster that don't come from Git. Argo CD doesn't prune
them (they carry no tracking annotation).

## The age key in the cluster

The fleet age key (`~/.config/sops/age/keys.txt` on dgx-1, see [age-key.md](age-key.md)) is also the Secret
**`argocd/sops-age`** (key `keys.txt`), mounted read-only (mode 0440, group 999) into the repo-server only, at
`/sops-age/keys.txt` (`SOPS_AGE_KEY_FILE`).

- **Why:** design D16 keeps secrets in Git encrypted with SOPS + age, and Argo CD has to decrypt them to apply
  them (P3.4). The alternatives (a second, cluster-only age key; a secrets operator) are in decision 0006.
- **Exposure:** the key can decrypt **every** SOPS file in the repo, not only `cluster/`. It is readable by
  cluster admins (the kubeconfig on dgx-1), by anything that can read Secrets in `argocd`, and by the repo-server
  process. k3s encrypts Secrets at rest in etcd (`secrets-encryption`), so it is not plain text in etcd snapshots
  on the Sparks and the Jetson. It never goes to GitHub.
- **If the cluster may be compromised:** rotate the age key (age-key.md "Rotation", which re-encrypts every file and
  rotates every secret), then replace the Secret:
  `kubectl -n argocd create secret generic sops-age --from-file=keys.txt=$HOME/.config/sops/age/keys.txt --dry-run=client -o yaml | kubectl apply -f -`
  and `kubectl -n argocd rollout restart deploy/argocd-repo-server`.

## Rotate the deploy key

```bash
cd ~/homelab && umask 077 && D=$(mktemp -d)
ssh-keygen -q -t ed25519 -N "" -C "argocd-homelab (read-only deploy key, Argo CD in k3s)" -f $D/id
gh repo deploy-key list -R nikghodki/homelab                       # note the old key's id
gh repo deploy-key add $D/id.pub -R nikghodki/homelab --title argocd-homelab     # read-only: never --allow-write
python3 - $D/id <<'PY'
import json, subprocess, sys
for k, f in (("argocd_deploy_key", sys.argv[1]), ("argocd_deploy_key_pub", sys.argv[1] + ".pub")):
    subprocess.run(["sops", "set", "secrets/argocd.enc.yaml", f'["{k}"]', json.dumps(open(f).read().strip() + ("\n" if k == "argocd_deploy_key" else ""))], check=True)
PY
shred -u $D/id $D/id.pub && rmdir $D
# re-create repo-homelab (step 2 of the bootstrap), check `argocd --core --kube-context argocd repo list` says Successful, then:
gh repo deploy-key delete <old-id> -R nikghodki/homelab
```

Commit `secrets/argocd.enc.yaml`.

## Sign-in and break-glass

Pocket ID sign-in: open `https://argocd.nghodki.ai` → "Log in via Pocket ID". The client secret is
`oidc_argocd_secret` in `secrets/console.enc.yaml` (made by `pocketid_sync.py`) and, as a copy for KSOPS,
`cluster/platform/argocd/extras/oidc.enc.yaml` (Secret `argocd-oidc`). If the client secret is ever rotated, update
both. `argocd-server` trusts Pocket ID's certificate through `rootCA` (the web CA) in `oidc.config`, and resolves
`id.nghodki.ai` through the `cluster-dns` CoreDNS zone.

If Pocket ID is down, use `argocd --core` on dgx-1 (above): it needs no Argo CD account. Only if the **UI** is
needed without Pocket ID, turn the local admin on for a while:

```bash
export KUBECONFIG=~/.kube/config PATH=$HOME/.local/bin:$PATH
# 1. Stop selfHeal from undoing it (root re-applies argocd's Application; argocd re-applies argocd-cm).
kubectl -n argocd patch application root   --type json -p '[{"op":"remove","path":"/spec/syncPolicy/automated"}]'
kubectl -n argocd patch application argocd --type json -p '[{"op":"remove","path":"/spec/syncPolicy/automated"}]'
# 2. A one-off password, then enable the account.
PW=$(openssl rand -base64 18); echo "$PW"      # in your own terminal only
kubectl -n argocd patch secret argocd-secret --type merge -p "{\"stringData\":{\"admin.password\":\"$(argocd account bcrypt --password "$PW")\",\"admin.passwordMtime\":\"$(date -u +%FT%TZ)\"}}"
kubectl -n argocd patch cm argocd-cm --type merge -p '{"data":{"admin.enabled":"true"}}'
# ... sign in as admin ...
# 3. Undo: remove the password, give the apps back to Git (admin.enabled is false again within seconds).
kubectl -n argocd patch secret argocd-secret --type json -p '[{"op":"remove","path":"/data/admin.password"},{"op":"remove","path":"/data/admin.passwordMtime"}]'
kubectl apply -f ~/homelab/cluster/bootstrap/apps/root.yaml
```

Tested 2026-11-15: admin login answered 200, and the undo restored `admin.enabled: false` and automated sync in 10 s.

## Read-only API account `ops-agent` (decision 0013)

The ops agent's `mcp-for-argocd` reads apps, history, diffs and resource trees with a local account: `accounts.ops-agent:
apiKey` (no login) and `g, ops-agent, role:readonly` in `values.yaml`. Its token is minted without a browser session
through core mode (the CLI talks to the cluster with the kubeconfig), and goes straight into SOPS:

```bash
export KUBECONFIG=~/.kube/config
argocd account generate-token --core -n argocd --account ops-agent --id ops-agent-mcp --expires-in 2160h \
  | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' \
  | sops set --value-stdin secrets/argocd.enc.yaml '["ops_agent_token"]'
```

Then copy it into the ops app's KSOPS Secret (`cluster/apps/ops/`), merge. Rotate every 90 days the same way with a
new `--id`, then `argocd account delete-token --core -n argocd --account ops-agent <old id>`. Check: the token can
`GET /api/v1/applications` and gets 403 on a sync.

## Upgrade

Bump `targetRevision` (chart version) in `cluster/bootstrap/apps/argocd.yaml` after reading the chart's and Argo
CD's upgrade notes; Argo CD upgrades itself on merge. Same for `kyverno.yaml` and `cnpg-operator.yaml`. Check the
values against the new chart with `helm template` first.

## Resources (measured 2026-11-15, cgroup `memory.current`; anon = process memory without page cache)

| Pod | Node | Request / limit | anon | incl. cache | peak |
|---|---|---|---|---|---|
| application-controller | dgx-1 | 384Mi / 768Mi | 377 MiB | 392 MiB | 491 MiB |
| repo-server | dgx-2 | 128Mi / 512Mi | 69 MiB | 368 MiB | 436 MiB |
| server | dgx-2 | 64Mi / 256Mi | 33 MiB | 35 MiB | 69 MiB |
| redis | dgx-1 | 16Mi / 96Mi | 12 MiB | 13 MiB | 15 MiB |
| **Argo CD total** | | 592Mi / 1632Mi | **491 MiB** | **808 MiB** | |

Nodes are where the scheduler put them at the time; any Spark is fine.

The application controller caches every object in the cluster; it was OOM-killed once at 512 Mi during the first
sync, hence 768 Mi and `GOMEMLIMIT=600MiB`. The repo-server's extra memory is page cache (Git and Helm charts),
which the kernel reclaims under the limit.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ComparisonError ... Error getting data key: 0 successful groups required` | KSOPS can't read the age key: `sops-age` missing, or not readable by uid 999 (`global.securityContext.fsGroup: 999`, mode 0440) |
| `ComparisonError ... app path does not exist` | `targetRevision` points at a branch without that folder |
| An app stays OutOfSync and flips back | something in the cluster mutates a field Argo CD sets; add `ignoreDifferences` to that Application |
| Login loops or "failed to query provider" | Pocket ID down, or `id.nghodki.ai` doesn't resolve in pods: `kubectl -n kube-system get cm coredns-custom`, and edge-dnsmasq on dgx-1 |
| `ArgoCDMetricsDown` but pods run | the host path to `10.43.0.101`: kube-proxy on dgx-2, or the `host-scrape` NetworkPolicy |
