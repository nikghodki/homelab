# agents

One folder per agent (plan P4.4):

```
agents/<name>/
  card.yaml      # agent card (A2A), scanned by a2a-scanner (.github/scripts/scan-agents.py; HIGH/CRITICAL fails CI)
  radar.yaml     # optional: {framework, path} for Agentic Radar (LangGraph, CrewAI, n8n, OpenAI Agents, AutoGen)
  scopes.yaml    # models, MCP servers/tools, A2A peers, NATS subjects
  budget.yaml    # monthly token limit, rate limit
  defenseclaw.yaml  # route (hook connector / Edge Connector / agent-gateway), tier
```

CI turns `scopes.yaml` into the agent's LiteLLM key settings and NATS account. Skills placed here are scanned by the
Cisco AI skill-scanner.
