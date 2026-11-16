"""Settings from the environment (cluster/apps/ops). Secrets come from files mounted from KSOPS Secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _file(path: str | None) -> str:
    if not path:
        return ""
    p = Path(path)
    return p.read_text().strip() if p.exists() else ""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    db_dsn: str = field(default_factory=lambda: _env("OPS_DB_DSN") or _file(_env("OPS_DB_DSN_FILE")))
    temporal_address: str = field(default_factory=lambda: _env("TEMPORAL_ADDRESS", "192.168.86.36:7233"))
    temporal_namespace: str = field(default_factory=lambda: _env("TEMPORAL_NAMESPACE", "ops-agent"))
    temporal_tls_dir: str = field(default_factory=lambda: _env("TEMPORAL_TLS_DIR", "/etc/ops-agent/temporal"))
    llm_base: str = field(default_factory=lambda: _env("LLM_BASE_URL", "http://10.43.0.150:4000/v1"))
    llm_key: str = field(default_factory=lambda: _file(_env("LLM_KEY_FILE", "/etc/ops-agent/secrets/litellm-key")))
    model_deep: str = field(default_factory=lambda: _env("MODEL_DEEP", "qwen3.8-27b"))
    model_fast: str = field(default_factory=lambda: _env("MODEL_FAST", "qwen3.8-27b-nothink"))
    daily_token_budget: int = field(default_factory=lambda: int(_env("DAILY_TOKEN_BUDGET", "1000000")))
    incident_token_cap: int = field(default_factory=lambda: int(_env("INCIDENT_TOKEN_CAP", "150000")))
    max_tool_calls: int = field(default_factory=lambda: int(_env("MAX_TOOL_CALLS", "25")))
    investigation_minutes: int = field(default_factory=lambda: int(_env("INVESTIGATION_MINUTES", "15")))
    mcp_grafana_url: str = field(default_factory=lambda: _env("MCP_GRAFANA_URL", "http://10.43.0.144:8000/mcp"))
    mcp_k8s_url: str = field(default_factory=lambda: _env("MCP_K8S_URL", "http://10.43.0.145:8080/mcp"))
    mcp_argocd_url: str = field(default_factory=lambda: _env("MCP_ARGOCD_URL", "http://10.43.0.146:3000/mcp"))
    grafana_public_url: str = field(default_factory=lambda: _env("GRAFANA_PUBLIC_URL", "https://grafana.nghodki.ai"))
    prom_ds_uid: str = field(default_factory=lambda: _env("PROM_DS_UID", "defenseclaw-prometheus"))
    loki_ds_uid: str = field(default_factory=lambda: _env("LOKI_DS_UID", "defenseclaw-loki"))
    opsro_key_file: str = field(default_factory=lambda: _env("OPSRO_KEY_FILE", "/etc/ops-agent/ssh/id_ed25519"))
    opsro_known_hosts: str = field(default_factory=lambda: _env("OPSRO_KNOWN_HOSTS", "/etc/ops-agent/ssh/known_hosts"))
    ntfy_url: str = field(default_factory=lambda: _env("NTFY_URL", "http://192.168.86.49:8085"))
    ntfy_topic: str = field(default_factory=lambda: _env("NTFY_TOPIC", "ops-agent"))
    ntfy_token: str = field(default_factory=lambda: _file(_env("NTFY_TOKEN_FILE", "/etc/ops-agent/secrets/ntfy-token")))
    portal_url: str = field(default_factory=lambda: _env("PORTAL_URL", "https://ops-agent.nghodki.ai"))
    origin_token: str = field(default_factory=lambda: _file(_env("ORIGIN_TOKEN_FILE", "/etc/ops-agent/secrets/origin-token")))
    ingest_token: str = field(default_factory=lambda: _file(_env("INGEST_TOKEN_FILE", "/etc/ops-agent/secrets/ingest-token")))
    heartbeat_url: str = field(default_factory=lambda: _env("HEARTBEAT_URL", ""))
    heartbeat_token: str = field(default_factory=lambda: _file(_env("HEARTBEAT_TOKEN_FILE", "/etc/ops-agent/secrets/heartbeat-token")))
    github_token: str = field(default_factory=lambda: _file(_env("GITHUB_TOKEN_FILE", "/etc/ops-agent/secrets/github-read-token")))
    github_repo: str = field(default_factory=lambda: _env("GITHUB_REPO", "nikghodki/homelab"))
    repo_dir: str = field(default_factory=lambda: _env("REPO_DIR", "/var/lib/ops-agent/repo"))
    repo_url: str = field(default_factory=lambda: _env("REPO_URL", "git@github.com:nikghodki/homelab.git"))
    deploy_key_file: str = field(default_factory=lambda: _env("DEPLOY_KEY_FILE", "/etc/ops-agent/git/deploy-key"))
    mode_file: str = field(default_factory=lambda: _env("MODE_FILE", "/etc/ops-agent/mode/mode.yaml"))
    quiet_start: str = field(default_factory=lambda: _env("QUIET_START", "22:30"))
    quiet_end: str = field(default_factory=lambda: _env("QUIET_END", "07:30"))
    timezone: str = field(default_factory=lambda: _env("TZ_NAME", "America/Los_Angeles"))
    task_queue: str = field(default_factory=lambda: _env("TASK_QUEUE", "ops-agent"))
    investigate_queue: str = field(default_factory=lambda: _env("INVESTIGATE_QUEUE", "ops-investigate"))


# The fleet as the agent sees it (architecture.md §3); host -> address for ops-ro, plus what lives there.
HOSTS = {
    "dgx-1": {"addr": "192.168.86.44", "role": "Spark: LiteLLM, DGXMM (model engines), NATS, Fleet broker, DefenseClaw gateway, k3s server"},
    "dgx-2": {"addr": "192.168.86.36", "role": "Spark: observe stack (VictoriaMetrics, vmalert, Alertmanager, Loki, Tempo, Grafana, Phoenix), Temporal (jobs), Pocket ID (console), MLflow (ml), restic, k3s server"},
    "jetson": {"addr": "192.168.86.211", "role": "Jetson: Home Assistant, Hermes agents, DefenseClaw (Hermes), ROS/Zenoh router, k3s server (tainted)"},
    "dell": {"addr": "192.168.86.49", "role": "Dell (Omarchy, LUKS, never reboot): Gatus, ntfy, status gate, Homepage, docs site, k3s agent"},
    "pi": {"addr": "192.168.86.39", "role": "Raspberry Pi: robot car, safety governor, picoclaw (read-only access only, never motion)"},
}

# Services whose failure hurts the family: always notify, even in quiet hours (decision 0013 Q10).
FAMILY_IMPACT = ("ha.nghodki.ai", "home assistant", "home-assistant", "webui.nghodki.ai", "open webui", "open-webui",
                 "dns", "edge-dns", "edge-caddy", "front door", "frontdoor", "edgefrontdoor", "edge vip")


def settings() -> Settings:
    return Settings()
