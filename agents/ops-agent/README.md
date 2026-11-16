# ops-agent

The ambient ops agent (decision 0013, [design](../../docs/ambient-agent-design.md), runbook
[runbooks/ops-agent.md](../../runbooks/ops-agent.md)). **Shadow mode**: it watches, investigates with read-only tools
and the local model, writes RCAs into its own database and notifies on ntfy topic `ops-agent`. It changes nothing.

| Module | What |
|---|---|
| `ingest/` | Alertmanager webhook, Kubernetes Warning events, change tracker (merges, Argo CD syncs), docs index, GitHub poller (off without a read token); correlation into incidents (`correlate.py`); starts one Temporal workflow per incident |
| `worker/` | Temporal worker (namespace `ops-agent`, mTLS): `IncidentWorkflow`, `DigestWorkflow` (08:00), the Stop switch watcher, heartbeat, metrics |
| `pipeline.py` | first look (fixed queries, `playbooks/first_look.yaml`) -> recall (runbooks, past incidents) -> investigate -> RCA |
| `tools/` | the curated read-only tools: mcp-grafana (metrics, logs), kubernetes-mcp-server, mcp-for-argocd, `ops-ro` host commands over SSH, docs search, memory, changes; redaction, caps, evidence store, replay clock |
| `investigate/` | our own tool-calling loop (`own_loop.py`) and the HolmesGPT adapter for the A1 bake-off (`holmes.py`, dgx-1 only) |
| `portal/` | ops-agent.nghodki.ai: Feed, Incident, Replay, Audit, Stop/Resume |
| `replay/` | the A0 replay harness and the gold set |

Commands: `ops-agent ingest | worker | portal | migrate | replay`.
Tests: `pytest agents/ops-agent/tests` (in CI's unit-test job).
