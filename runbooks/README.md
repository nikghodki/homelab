# runbooks

One file per incident (architecture §17.2). To be written in plan P3.9:

- DefenseClaw down
- Model alias down
- Spark reboot
- Quorum loss
- Disk full
- Agent misbehaving (freeze)
- Robot misbehaving (e-stop)
- Security alert (quarantine)
- Wi-Fi outage
- Power cut
- Bad deploy (revert)

Operational how-tos (not incidents): [simulation.md](simulation.md) (Isaac Lab and MuJoCo jobs on dgx-2),
[mlflow.md](mlflow.md) (MLflow tracking server on dgx-2),
[robot-safety.md](robot-safety.md) (the Pi safety governor: e-stop, limits, the on-blocks test),
[k3s.md](k3s.md) (the cluster: nodes, add/remove/roll back a node, snapshots, moving to wired),
[alerting.md](alerting.md) (how alerts reach the phone: Gatus and ntfy on the Dell, Alertmanager on dgx-2),
[argocd.md](argocd.md) (GitOps: bootstrap, add an app, break-glass, the deploy key and the age key in the cluster),
[kyverno.md](kyverno.md) (admission policies, Audit → Enforce).
