from fleet_metrics import services

def make_run(table):
    def run(cmd, **kw):
        key = " ".join(cmd[:3])
        class R:
            returncode = table.get(key, (1, ""))[0]
            stdout = table.get(key, (1, ""))[1]
        return R()
    return run

def test_units_active_and_inactive():
    run = make_run({
        "systemctl is-active control-center.service": (0, "active\n"),
        "systemctl is-active vision-vlm.service": (3, "inactive\n"),
    })
    out = services.collect_services(["control-center.service", "vision-vlm.service"], run=run)
    units = [s for s in out if s["kind"] == "unit"]
    assert {"name": "control-center.service", "kind": "unit", "up": True, "detail": "active"} in units
    assert {"name": "vision-vlm.service", "kind": "unit", "up": False, "detail": "inactive"} in units

def test_docker_discovered():
    run = make_run({
        "docker ps -a": (0, "vllm-hermes\trunning\tUp 6 days\nwhisper\texited\tExited (0)\n"),
    })
    out = services.collect_services([], run=run)
    docker = [s for s in out if s["kind"] == "docker"]
    assert {"name": "vllm-hermes", "kind": "docker", "up": True, "detail": "Up 6 days"} in docker
    assert {"name": "whisper", "kind": "docker", "up": False, "detail": "Exited (0)"} in docker

def test_docker_absent_is_not_fatal():
    def run(cmd, **kw): raise FileNotFoundError()
    assert services.collect_services([], run=run) == []

def test_ollama_running():
    run = make_run({"ollama ps": (0, "NAME\tID\tSIZE\nqwen3:latest\tabc\t4GB\n")})
    out = services.collect_services([], run=run)
    assert {"name": "qwen3:latest", "kind": "ollama", "up": True, "detail": "running"} in out
