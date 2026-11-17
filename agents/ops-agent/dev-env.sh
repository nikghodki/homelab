#!/usr/bin/env bash
# Run an ops-agent command (the replay harness) on dgx-1 with the agent's credentials in a private temp dir (removed on exit).
#   agents/ops-agent/dev-env.sh <command...>   e.g. dev-env.sh python -m ops_agent replay run --gold G4
# Needs: ~/.venvs/ops-agent (uv venv + requirements.txt), sops and the age key, kubectl admin, ~/homelab on main.
set -euo pipefail
export PATH=$HOME/.local/bin:$PATH KUBECONFIG=$HOME/.kube/config
t=$(mktemp -d); chmod 700 "$t"; trap 'rm -rf "$t"' EXIT
S=~/homelab/cluster/apps/ops/ops-agent.enc.yaml
sops -d --extract '["stringData"]["mcp-grafana-auth"]' "$S" > "$t"/mcp-grafana
sops -d --extract '["stringData"]["mcp-argocd-auth"]' "$S" > "$t"/mcp-argocd
sops -d --extract '["ops_agent_eval_litellm_key"]' ~/homelab/secrets/litellm.enc.yaml > "$t"/litellm-key   # the evaluation key (runbooks/ops-agent.md)
sops -d --extract '["opsro_ssh_key"]' ~/homelab/secrets/ops-agent.enc.yaml > "$t"/id; chmod 600 "$t"/id
for h in 192.168.86.44 192.168.86.36 192.168.86.211 192.168.86.49 192.168.86.39; do ssh-keygen -F $h -f ~/.ssh/known_hosts | grep -v "^#"; done > "$t"/kh
kubectl -n ops get secret ops-db-app -o jsonpath='{.data.uri}' | base64 -d | sed 's#@ops-db-rw[^:/]*:#@10.43.0.143:#' > "$t"/dsn
export MCP_TOKEN_DIR="$t" OPSRO_KEY_FILE="$t"/id OPSRO_KNOWN_HOSTS="$t"/kh LLM_KEY_FILE="$t"/litellm-key OPS_DB_DSN_FILE="$t"/dsn \
       LLM_BASE_URL=http://10.43.0.150:4000/v1 MODE_FILE=/nonexistent
cd "$(dirname "$0")"
PATH=$HOME/.venvs/ops-agent/bin:$PATH "$@"
