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
[kyverno.md](kyverno.md) (admission policies, Audit → Enforce),
[mcp-admission.md](mcp-admission.md) (approved MCP servers, DefenseClaw admission, nightly tool drift check),
[hardening.md](hardening.md) (Lynis remediation: host hardening, documented exceptions, roll back),
[edge.md](edge.md) (the `*.nghodki.ai` front door in k3s: kube-vip, CoreDNS, Caddy; adding routes; the cutover),
[docs-site.md](docs-site.md) (the private docs site on the Dell: build, hosting, updates, roll back, adding a page),
[ci-scanners.md](ci-scanners.md) (what CI scans, accepted vulnerabilities with expiring ignores, shellcheck),
[jetson-services.md](jetson-services.md) (Home Assistant and LiveKit on the Jetson: deploy, check, upgrade),
[aibom.md](aibom.md) (Cisco AIBOM nightly inventory; the Jetson's images are scanned on dgx-2).
