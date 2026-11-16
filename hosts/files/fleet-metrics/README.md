# fleet-metrics

Standalone agent exposing host resource metrics and service status via HTTP. GET `/metrics` returns CPU, memory, GPU, and uptime; GET `/services` returns enumerated systemd units, docker containers, and ollama models. No third-party dependencies.

Deploy: Ansible role `fleet_metrics` (`hosts/playbooks/fleet-metrics.yml`, also in `site.yml`). It installs a system unit `fleet-metrics.service` running as user `fleetmetrics` (in the `docker` group for container status). `FLEET_UNITS` (comma-separated systemd unit names) comes from `fleet_metrics_units`, which no host sets today. Verify: `curl localhost:9109/metrics`.
