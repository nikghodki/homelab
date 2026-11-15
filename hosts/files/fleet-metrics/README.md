# fleet-metrics

Standalone agent exposing host resource metrics and service status via HTTP. GET `/metrics` returns CPU, memory, GPU, and uptime; GET `/services` returns enumerated systemd units, docker containers, and ollama models. No third-party dependencies.

Deploy: `scp -r fleet-metrics <host>:~/ && ssh <host> "systemctl --user enable --now fleet-metrics"`. Set `FLEET_UNITS` env var per host (comma-separated systemd unit names) and verify: `curl localhost:9109/metrics`. For docker introspection, ensure the user is in the `docker` group.
