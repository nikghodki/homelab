# cluster

Kubernetes (k3s) applications, synced by Argo CD (plan phase 3). One folder per namespace in
[architecture §3.1](../docs/architecture.md). Images must be pinned by digest and signed; Kyverno rejects others.
