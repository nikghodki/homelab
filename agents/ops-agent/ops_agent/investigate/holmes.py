"""HolmesGPT as the investigation engine (A1 bake-off, decision 0013 Q5). Runs only where HolmesGPT is installed
(the replay harness on dgx-1), never in the cluster image.

Fair comparison: HolmesGPT gets no built-in toolsets (no kubectl, no bash, no Prometheus of its own); its only tools
are ours, served over MCP by the same gateway (same redaction, caps, replay clock and evidence store), and the same
model through the same LiteLLM key. Its answer is asked for in the submit_rca shape so both are scored the same way.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import uvicorn
import yaml

from ..config import settings
from ..tools import mcp_server
from ..tools.gateway import Gateway, ToolContext
from . import prompts
from .own_loop import LoopResult

HOLMES = os.environ.get("HOLMES_BIN", str(Path.home() / ".venvs/holmes/bin/holmes"))

FORMAT = """When you are done, end your answer with ONE JSON object (and nothing after it) with these keys:
summary, impact, root_cause, confidence (high|medium|low), claims (list of {claim, evidence: [refs like "E3"]}),
timeline (list), ruled_out (list), fix_options (list of {description, kind: pr|manual|live|none, risk}),
verification, follow_ups (list), needs (list). Cite the evidence refs that the tools return (E1, E2, ...)."""


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _last_json(text: str) -> dict:
    for m in reversed(list(re.finditer(r"\{", text))):
        frag = text[m.start():]
        depth = 0
        for i, ch in enumerate(frag):
            depth += ch == "{"
            depth -= ch == "}"
            if depth == 0:
                try:
                    d = json.loads(frag[:i + 1])
                    if isinstance(d, dict) and "root_cause" in d:
                        return d
                except ValueError:
                    pass
                break
    return {}


async def investigate(gw: Gateway, ctx: ToolContext, brief: str, first_look: str, recall: str) -> LoopResult:
    s = settings()
    token = secrets.token_urlsafe(16)
    counter: dict = {"max": s.max_tool_calls}
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(mcp_server.app(gw, ctx, token, counter), host="127.0.0.1", port=port,
                                           log_level="warning"))
    task = asyncio.create_task(server.serve())
    tmp = Path(tempfile.mkdtemp(prefix="holmes-"))
    t0 = time.monotonic()
    res = LoopResult(rca={})
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        cfg = {"mcp_servers": {"ops_tools": {
            "description": "The home fleet's read-only tools: metrics, logs, k3s, Argo CD, host commands, runbooks, "
                           "past incidents, changes. Use these for every question.",
            "config": {"url": f"http://127.0.0.1:{port}/mcp", "mode": "streamable-http",
                       "headers": {"Authorization": f"Bearer {token}"}}}}}
        # every built-in toolset off: only our MCP tools
        builtin = Path(HOLMES).parent.parent / "lib/python3.12/site-packages/holmes/plugins/toolsets"
        names = set()
        for f in builtin.rglob("*.yaml"):
            try:
                names |= set((yaml.safe_load(f.read_text()) or {}).get("toolsets", {}).keys())
            except Exception:
                pass
        # toolsets defined in Python (not in the YAML files above)
        names |= {"kubernetes/logs", "bash", "internet", "connectivity_check", "kubernetes/kube-prometheus-stack",
                  "docker/core", "skills", "kubernetes/live-metrics", "helm/core"}
        # Keep HolmesGPT's own planning tool (core_investigation: its to-do list), part of the engine being compared.
        names.discard("core_investigation")
        cfg["toolsets"] = {n: {"enabled": False} for n in sorted(names)}
        (tmp / "config.yaml").write_text(yaml.safe_dump(cfg))
        (tmp / "prompt.txt").write_text(f"{prompts.SYSTEM}\n\n{brief}\n\nFIRST LOOK (deterministic queries):\n"
                                        f"{first_look}\n\nRECALL:\n{recall}\n\nInvestigate with the ops_tools tools. {FORMAT}")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp), "OPENAI_API_BASE": s.llm_base, "OPENAI_API_KEY": s.llm_key,
               "KUBECONFIG": "/dev/null", "HOLMES_DISABLE_TELEMETRY": "true", "DISABLE_PROMETHEUS_TOOLSET": "true",
               "LANG": "C.UTF-8"}
        cmd = [HOLMES, "ask", "--prompt-file", str(tmp / "prompt.txt"), "--model", f"openai/{s.model_deep}",
               "--config", str(tmp / "config.yaml"), "--max-steps", str(s.max_tool_calls + 5), "--no-interactive",
               "--json-output-file", str(tmp / "out.json"), "--no-echo", "--bash-always-deny"]
        proc = await asyncio.create_subprocess_exec(*cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=s.investigation_minutes * 60 + 120)
        except asyncio.TimeoutError:
            proc.kill()
            out = b""
            res.notes.append("HolmesGPT timed out")
        text = out.decode(errors="replace")
        if os.environ.get("OPS_HOLMES_LOG"):
            with open(os.environ["OPS_HOLMES_LOG"], "a") as f:
                f.write(text)
        answer = ""
        if (tmp / "out.json").exists():
            try:
                j = json.loads((tmp / "out.json").read_text())
                answer = j.get("result") or j.get("analysis") or json.dumps(j)
            except ValueError:
                pass
        res.rca = _last_json(answer or text)
        if not res.rca:
            res.notes.append("HolmesGPT gave no structured answer; raw: " + (answer or text)[-1500:])
    finally:
        server.should_exit = True
        await task
        shutil.rmtree(tmp, ignore_errors=True)
    res.tool_calls = counter.get("calls", 0)
    res.refs = counter.get("refs", [])
    res.seconds = time.monotonic() - t0
    return res
