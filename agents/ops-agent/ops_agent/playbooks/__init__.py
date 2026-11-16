"""First-look playbooks (YAML in this package)."""
from __future__ import annotations

from pathlib import Path

import yaml

LOKI_HOST = {"dgx-1": "spark-83dc", "dgx-2": "nikghodki-dgx-2", "jetson": "nikhil-jetson",
             "dell": "nikghodki-omarchy-local", "pi": "nikghodki-raspberry"}
FLEET_HOST = {"dell": "omarchy"}


def load() -> dict:
    return yaml.safe_load((Path(__file__).parent / "first_look.yaml").read_text())


def steps_for(klass: str, labels: dict, host: str) -> tuple[list[dict], str]:
    pb = load()
    cls = pb["classes"].get(klass) or pb["classes"]["generic"]
    v = {"host": host or "dgx-2", "loki_host": LOKI_HOST.get(host, host), "fleet_host": FLEET_HOST.get(host, host),
         "namespace": labels.get("namespace", ""), "name": labels.get("name") or labels.get("deployment") or labels.get("pod", ""),
         "alertname": labels.get("alertname", ""), "run_id": labels.get("run_id", ""), "endpoint": labels.get("name", ""), "group": labels.get("group", "")}

    def fill(x):
        if isinstance(x, str):
            for k, val in v.items():
                x = x.replace("{" + k + "}", str(val))
            return x
        if isinstance(x, dict):
            return {k: fill(val) for k, val in x.items()}
        return x

    steps = [fill(s) for s in pb["common"] + cls.get("steps", [])]
    # skip steps whose placeholders had no value (e.g. no namespace on a host alert)
    steps = [s for s in steps if not any(val == "" for val in s["args"].values()
                                         if isinstance(val, str))]
    return steps, fill(cls.get("runbook", ""))
