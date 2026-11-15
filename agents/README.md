# agents

One folder per agent (plan P4.4):

```
agents/<name>/
  card.yaml      # agent card (A2A), scanned by a2a-scanner
  scopes.yaml    # models, MCP servers/tools, A2A peers, NATS subjects
  budget.yaml    # monthly token limit, rate limit
  defenseclaw.yaml  # route (hook connector / Edge Connector / agent-gateway), tier
```

CI turns `scopes.yaml` into the agent's LiteLLM key settings and NATS account. Skills placed here are scanned by the
Cisco AI skill-scanner.
