# policies

| Folder | Holds |
|---|---|
| `defenseclaw/` | DefenseClaw rule packs, CEL/OPA policies, protected files, `asset_policy` allow/block lists |
| `kyverno/` | Cluster admission rules (signed images only, no privileged pods except an allowlist, limits required) |
| `tailscale/` | Tailscale ACL (`tailscale.hujson`) with the tags from architecture §4.2 |

## DefenseClaw

`defenseclaw/homelab.yaml` is the fleet policy, based on the built-in `default` preset with these changes:

- MCP CRITICAL/HIGH findings block install and runtime (all MCP tools reach agents through LiteLLM).
- Human-in-the-loop is on at MEDIUM.
- Rescans run every 30 minutes.

`hosts/playbooks/defenseclaw.yml` copies the policy to every host that has the DefenseClaw CLI and activates it. `tests/` runs in CI and fails if an edit loosens these rules.

Edit the YAML by hand. `defenseclaw policy edit scanner -p` writes lowercase severity keys next to the uppercase ones, and the test catches this.

`defenseclaw/edge/` holds Edge Connector policies, one per tenant/fleet. They are pushed through the Fleet API, which compiles them, signs them and sends them over MQTT. See `runbooks/edge-connector.md`.
