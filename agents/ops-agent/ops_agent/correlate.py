"""Events -> incidents: normalise, classify, fingerprint, correlate (design §4.2).

Pure functions here (unit-tested); ingest/app.py does the I/O.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field

from .config import FAMILY_IMPACT

# alertname (or prefix) -> playbook class
CLASS_BY_ALERT = [
    (r"^(FleetHostSilent|AlertingHostDown|K3sEtcdMemberDown)$", "host_down"),
    (r"^FleetDisk", "disk"),
    (r"^(FleetMemoryLow|FleetGpuHot|FleetGpuMetricsMissing)$", "gpu_memory"),
    (r"^(FleetHostHot|FleetPiHot)$", "thermal"),
    (r"^ArgoCD", "argocd"),
    (r"^Kyverno", "kyverno"),
    (r"^(EdgeFrontDoorDown|EdgeReplicasDown|KubeVip)", "front_door"),
    (r"^(K3sApiDown|K3sEtcdQuorumLost|KubeStateMetricsDown)$", "k3s"),
    (r"^ObservabilityComponentDown$", "observability"),
    (r"^AlertDeliveryFailing$", "alert_delivery"),
    (r"^DefenseClaw", "defenseclaw"),
    (r"^(SafetyGovernor|Edge(Device|Canary|Ota))", "robot_edge"),
    (r"^GatusEndpointFailing$", "gatus_check"),
    (r"^OpsLogErrorAnomaly$", "log_anomaly"),
    (r"^OpsAgent", "self"),
]

K8S_REASON_CLASS = {
    "BackOff": "container_restart", "CrashLoopBackOff": "container_restart", "OOMKilling": "container_restart",
    "OOMKilled": "container_restart", "FailedScheduling": "k8s_workload", "FailedMount": "k8s_workload",
    "Unhealthy": "k8s_workload", "PolicyViolation": "kyverno", "FailedCreate": "k8s_workload",
    "Evicted": "k8s_workload", "NodeNotReady": "host_down",
}

# Gatus endpoint name -> playbook class hints
GATUS_CLASS = [
    (r"refuses direct access|gate", "gatus_check"),
    (r"(?i)dns|front door|\.nghodki\.ai|vip", "front_door"),
    (r"(?i)ssh", "host_down"),
    (r"(?i)litellm|model|dgxmm|dgxmanager", "model_plane"),
    (r"(?i)pocket id|auth\.|edge-auth|sign", "sign_in"),
]

WATCHED_K8S_REASONS = set(K8S_REASON_CLASS)


def classify_alert(name: str, labels: dict) -> str:
    for rx, k in CLASS_BY_ALERT:
        if re.search(rx, name):
            if k == "gatus_check":
                ep = labels.get("name", "")
                for grx, gk in GATUS_CLASS:
                    if re.search(grx, ep):
                        return gk if gk != "gatus_check" else "gatus_check"
            return k
    return "generic"


def family_impact(*texts: str) -> bool:
    t = " ".join(x.lower() for x in texts if x)
    return any(w in t for w in FAMILY_IMPACT)


def host_of(labels: dict) -> str:
    h = labels.get("host_name") or labels.get("host") or labels.get("node") or labels.get("instance") or ""
    h = h.split(":")[0]
    alias = {"192.168.86.44": "dgx-1", "192.168.86.36": "dgx-2", "192.168.86.211": "jetson", "192.168.86.49": "dell",
             "192.168.86.39": "pi", "spark-83dc": "dgx-1", "omarchy": "dell", "nikjetson": "jetson"}
    return alias.get(h, h)


@dataclass
class Event:
    source: str
    occurred_at: dt.datetime
    fingerprint: str
    status: str
    summary: str
    labels: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    klass: str = "generic"
    severity: str = "warning"

    @property
    def payload_sha(self) -> str:
        return hashlib.sha256(json.dumps(self.payload, sort_keys=True, default=str).encode()).hexdigest()

    def incident_key(self) -> str:
        """One open incident per key. Alerts: alertname + the labels that name a thing; k8s: object + reason class."""
        l = self.labels
        if self.source == "k8s":
            return f"k8s:{l.get('namespace')}/{l.get('kind')}/{l.get('name')}:{self.klass}"
        if self.source == "github":
            return f"ci:{l.get('workflow')}:{l.get('failure_class')}:{l.get('branch')}"
        parts = [l.get("alertname", "?")]
        for k in ("host_name", "namespace", "name", "app", "deployment", "job", "service", "endpoint", "group"):
            if l.get(k):
                parts.append(f"{k}={l[k]}")
        return "alert:" + ",".join(parts)


def parse_time(s: str | None) -> dt.datetime:
    if not s or s.startswith("0001-"):
        return dt.datetime.now(dt.timezone.utc)
    s = s.replace("Z", "+00:00")
    # Alertmanager sends nanoseconds sometimes
    m = re.match(r"(.*\.\d{6})\d*(.*)", s)
    if m:
        s = m.group(1) + m.group(2)
    return dt.datetime.fromisoformat(s)


def from_alertmanager(body: dict) -> list[Event]:
    out = []
    for a in body.get("alerts", []):
        labels = dict(a.get("labels", {}))
        ann = a.get("annotations", {})
        name = labels.get("alertname", "?")
        if name == "Watchdog":
            continue
        k = classify_alert(name, labels)
        summary = ann.get("summary") or ann.get("description") or name
        status = a.get("status", "firing")
        out.append(Event(
            source="alertmanager",
            occurred_at=parse_time(a.get("startsAt") if status == "firing" else a.get("endsAt")),
            fingerprint=a.get("fingerprint") or hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest()[:16],
            status=status, summary=f"{name}: {summary}"[:500], labels=labels,
            payload={"labels": labels, "annotations": ann, "startsAt": a.get("startsAt"), "endsAt": a.get("endsAt"),
                     "generatorURL": a.get("generatorURL")},
            klass=k, severity=labels.get("severity", "warning")))
    return out


def from_k8s_event(ev: dict) -> Event | None:
    if ev.get("type") != "Warning":
        return None
    reason = ev.get("reason", "")
    if reason not in WATCHED_K8S_REASONS:
        return None
    obj = ev.get("involvedObject") or ev.get("regarding") or {}
    ns = obj.get("namespace") or ev.get("metadata", {}).get("namespace", "")
    count = int(ev.get("count") or (ev.get("series") or {}).get("count") or 1)
    # a failed probe, a pod waiting for a node or a restart back-off during a rollout is normal once or twice
    if reason in ("Unhealthy", "FailedScheduling", "BackOff") and count < 3:
        return None
    labels = {"namespace": ns, "kind": obj.get("kind", ""), "name": obj.get("name", ""), "reason": reason,
              "node": (ev.get("source") or {}).get("host", "") or ev.get("reportingInstance", "")}
    t = ev.get("lastTimestamp") or ev.get("eventTime") or ev.get("metadata", {}).get("creationTimestamp")
    msg = (ev.get("message") or ev.get("note") or "")[:400]
    return Event(source="k8s", occurred_at=parse_time(t),
                 fingerprint=hashlib.sha256(f"{ns}/{obj.get('kind')}/{obj.get('name')}/{reason}".encode()).hexdigest()[:16],
                 status="warning", summary=f"{reason} {obj.get('kind')}/{ns}/{obj.get('name')}: {msg}"[:500],
                 labels=labels, payload={"reason": reason, "message": msg, "count": ev.get("count")},
                 klass=K8S_REASON_CLASS.get(reason, "k8s_workload"),
                 severity="warning")


# Components a path or an alert belongs to, for "during-change" correlation.
COMPONENT_PATHS = [
    (r"^hosts/stacks/observe|vmalert|alertmanager|grafana|loki", "observability"),
    (r"^hosts/stacks/alerting|gatus|ntfy", "alerting"),
    (r"^hosts/stacks/jobs|temporal", "temporal"),
    (r"^hosts/stacks/litellm|litellm", "model_plane"),
    (r"^cluster/platform/edge|edge|caddy|names\.txt", "front_door"),
    (r"^cluster/platform/kyverno|^policies/kyverno|kyverno", "kyverno"),
    (r"^cluster/platform/argocd|^cluster/bootstrap|argocd", "argocd"),
    (r"^cluster/platform/kube-vip|kube-vip", "front_door"),
    (r"^hosts/roles/k3s|k3s|etcd", "k3s"),
    (r"^hosts/stacks/console|pocket|identity/", "sign_in"),
    (r"^hosts/stacks/home-assistant|home-assistant", "home_assistant"),
    (r"^hosts/roles/fleet_metrics|fleet-metrics|fleet_metrics", "observability"),
    (r"^cluster/apps/(?P<app>[^/]+)", "app"),
]

CLASS_COMPONENTS = {
    "observability": {"observability"}, "alert_delivery": {"alerting", "observability"}, "argocd": {"argocd"},
    "kyverno": {"kyverno", "argocd"}, "front_door": {"front_door", "k3s"}, "k3s": {"k3s"},
    "sign_in": {"sign_in", "front_door"}, "gatus_check": {"alerting", "front_door", "sign_in"},
    "model_plane": {"model_plane"}, "container_restart": {"app", "k3s"}, "k8s_workload": {"app", "k3s"},
    "gpu_memory": {"model_plane"}, "host_down": {"k3s"},
}


def components_for_paths(paths: list[str]) -> list[str]:
    out: set[str] = set()
    for p in paths:
        for rx, comp in COMPONENT_PATHS:
            m = re.search(rx, p)
            if m:
                out.add(comp if comp != "app" else f"app:{m.group('app')}")
    return sorted(out)


def change_matches(klass: str, labels: dict, change_components: list[str]) -> bool:
    want = CLASS_COMPONENTS.get(klass, set())
    for c in change_components:
        if c in want:
            return True
        if c.startswith("app:") and ("app" in want) and c[4:] == labels.get("namespace"):
            return True
    return False


class StormDetector:
    """More than `limit` new events in `window` -> storm mode until `quiet` passes without new events."""

    def __init__(self, limit: int = 10, window: int = 300, quiet: int = 600):
        self.limit, self.window, self.quiet = limit, window, quiet
        self.times: list[float] = []
        self.storm_since: float | None = None

    def add(self, t: float) -> bool:
        self.times = [x for x in self.times if t - x <= max(self.window, self.quiet)] + [t]
        recent = [x for x in self.times if t - x <= self.window]
        if self.storm_since is None and len(recent) > self.limit:
            self.storm_since = t
        return self.storm_since is not None

    def active(self, now: float) -> bool:
        if self.storm_since is not None and self.times and now - self.times[-1] > self.quiet:
            self.storm_since = None
        return self.storm_since is not None


def is_flapping(transitions_last_hour: int) -> bool:
    return transitions_last_hour > 5
