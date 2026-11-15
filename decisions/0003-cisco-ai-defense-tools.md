# 0003: Which Cisco AI Defense tools the fleet uses

- Date: 2026-11-15
- Status: decided

## Context

The fleet already runs several tools from [github.com/cisco-ai-defense](https://github.com/cisco-ai-defense)
(DefenseClaw and three scanners). The org has 21 public repositories; this records a status for each one so the
question does not have to be re-researched. Listed with
`gh api --paginate "orgs/cisco-ai-defense/repos?per_page=100"`, public repositories only (2026-11-15).

Two facts decide most rows:

- The `ai-defense-*` integrations, `ai-defense-cli` and `ai-defense-hybrid` are clients or connectors for the paid
  **Cisco AI Defense** cloud service. Their READMEs require an AI Defense API key (and a tenant inspection URL or
  region); the fleet has no tenant. The local equivalents are DefenseClaw and its LiteLLM guardrail (P2.4).
- The fleet has no populated RAG / vector store yet: Open WebUI on dgx-1 uses its built-in Chroma
  (`vector_db/chroma.sqlite3`, 188 KB, no uploaded files), and there is no Weaviate, Qdrant or pgvector.

## Decision

| Repository | Status | Reason |
|---|---|---|
| defenseclaw | **in use** (1.0.9) | Per-user on the Jetson and dgx-1 (Fleet gateway), Edge Connector on the Pi, dashboards and alert rules synced by `defenseclaw-bundle.py`, policy in `policies/defenseclaw/`, nightly `defenseclaw aibom scan`. |
| mcp-scanner | **in use** (4.8.7) | CI scans `tools/*/tools.json` (YARA, offline): now 2 servers, 44 tools, with per-tool hashes (`tools.sha256`, P4.3). |
| skill-scanner | **in use** (2.3.2) | CI `scan-skills.sh`; also inside DefenseClaw on the Jetson. |
| a2a-scanner | **in use** (1.0.1) | CI `scan-agents.py` on `agents/*/card.yaml`. |
| aibom | **adopted now** (`cisco-aibom` 1.10.1) | CI job on every PR (artifact `aibom`) and nightly fleet inventory of agent code and AI images on dgx-1, dgx-2, Jetson and Pi (role `cisco_aibom`, Grafana "AI inventory", runbooks/aibom.md). Deterministic-only: no LLM configured. |
| model-provenance-kit | **planned** (P2.5) | Provenance of downloaded weights against its reference DB, as an advisory check after a DGXMM download (docs/model-supply-chain.md). Waits for the DGXMM session. |
| pickle-fuzzer | **planned** (P2.5) | Self-test of the pickle scanner chosen for DGXMM downloads (generated pickles + malicious seeds, weekly, dgx-2). It tests scanners; it does not scan models. |
| project-quarry | **planned** (after P2.6) | Alpha detection DSL over agent conversations. Once Hermes / LiteLLM traces land in Phoenix (P2.6), a nightly batch on dgx-2 next to Phoenix could run its rules over exported traces and log matches to Loki. Waits for P2.6 and a stable DSL (it may change before 1.0). |
| adversarial-hubness-detector | **planned** (no plan item yet) | Applies once a RAG store has content. It supports FAISS, Pinecone, Qdrant and Weaviate, not Chroma, so Open WebUI's knowledge base would need its embeddings exported to FAISS or a move to Qdrant first. |
| ai-defense-litellm | not adopted (unless a tenant is available) | LiteLLM hook calling `https://<tenant>.ai-defense.cisco.com/inspect/chat` with an API key. DefenseClaw's guardrail plugin covers LiteLLM locally (P2.4). |
| ai-defense-python-sdk | not adopted (unless a tenant is available) | Client for the AI Defense inspection and management APIs; needs API keys. |
| ai-defense-cli | not adopted (unless a tenant is available) | CLI for the AI Defense cloud; needs `AI_DEFENSE_API_KEY`. |
| ai-defense-hybrid | not adopted (unless a tenant is available) | Terraform / Kubernetes templates for the AI Defense Hybrid Connector on cloud providers; part of a paid deployment. |
| ai-defense-kong-plugin | not adopted | Needs an AI Defense endpoint and key, and the fleet has no Kong (Caddy and nginx). |
| ai-defense-langchain-middleware | not adopted | Needs an AI Defense key and region; no fleet agent is built on LangChain. |
| ai-defense-google-adk | not adopted | Needs an AI Defense account and key; no fleet agent uses Google ADK. |
| fpr-model-calibration | not adopted | Research library (FPRCal) that calibrates a detector's scores to a fixed false-positive scale; only relevant when we train and release our own detectors. |
| securebert2 | not adopted | Research model: a cybersecurity-tuned ModernBERT encoder. No fleet task needs it; a candidate embedding model if a security knowledge base is ever built. |
| litellm (fork) | not adopted | The fleet runs upstream LiteLLM (`ghcr.io/berriai/litellm`, pinned); the fork is not needed. |
| litellm-docs (fork) | not adopted | Documentation fork; not needed. |
| .github | n/a | Org profile and community files, not a tool. |

## Alternatives considered

- **Cisco AI Defense tenant** (cloud inspection for LiteLLM, MCP and agents): would make the `ai-defense-*` rows
  usable, but it is a paid service and sends prompts to a cloud tenant; DefenseClaw does the same job locally.
  Revisit if a tenant becomes available.
- **AIBOM with LLM enrichment**: the agentic stage confirms or drops candidates and adds identifiers. It needs an
  LLM; pointing it at LiteLLM needs a dedicated virtual key, which waits for the LiteLLM session (runbooks/aibom.md).

## Consequences

- Five tools are now in use (DefenseClaw, mcp-scanner, skill-scanner, a2a-scanner, AIBOM); three are queued behind
  P2.5 and P2.6; one waits for a RAG store.
- Two AIBOMs exist on the Jetson: DefenseClaw's (what Hermes has connected: skills, plugins, MCP servers) and
  Cisco AIBOM (what the code and images contain). runbooks/aibom.md explains the difference.
- Re-check this table when the org publishes a new public repository or a tenant becomes available.
