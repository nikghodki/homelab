# cluster/apps

Workloads, one folder per app, deployed by Argo CD in project `apps` (namespaced resources plus their Namespace;
not `argocd`, `kube-system`, `kyverno` or `cnpg-system`). Empty until P3.7 moves the Docker services in.

Add an app:

1. `cluster/apps/<name>/`: plain manifests or a `kustomization.yaml`; a Namespace named after the app; requests,
   limits and a `nodeSelector` on every pod; images pinned by digest. Secrets as SOPS `*.enc.yaml` plus a KSOPS
   generator, like `_smoke/`.
2. `cluster/bootstrap/apps/<name>.yaml`: an Application (`project: apps`, `targetRevision: main`, automated sync
   with prune and selfHeal; copy `smoke.yaml`).
3. PR. CI runs kubeconform and the Kyverno CLI. After the merge, `root` picks it up within about 3 minutes.

`_smoke/` is the SOPS canary: a Namespace and a KSOPS-decrypted Secret, no pods (runbooks/argocd.md).
