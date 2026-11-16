---
title: OpenBot (pending decision 0004)
description: The planned computer-use agent on the Dell, why it is blocked, the options, and what the user has to decide.
---

D13 picked **CopilotKit/OpenBot** for an agent with its own sandboxed computer (container with Chromium, `/workspace`,
bash; gVisor; per-bot egress allowlist; audit) on Omarchy. Decision 0004 (proposed, **pending the user**) checked it
against primary sources on 2026-11-15:

- OpenBot (MIT, v1.0.x, very young) won't start without **CopilotKit Intelligence** (closed, separately licensed).
- Intelligence comes as managed (free tier: 1,000 interactions/month), self-hosted (paid; online usage reporting) or a
  local preview that is macOS-only and needs 4 CPUs, 12 GiB RAM and 40 GiB: it doesn't fit the Dell, and the Sparks
  are arm64 Linux, which the preview doesn't support either.
- OpenBot's own images exist for amd64 and arm64; one bot computer is about 0.4–0.5 GB measured.

| Option | Summary |
|---|---|
| A | OpenBot + managed Intelligence (free tier): full feature set, but threads and memory leave the home lab |
| B | OpenBot + local Intelligence: doesn't fit the Dell |
| C | OpenBot + self-hosted Intelligence: paid, needs bigger amd64 nodes |
| **D (recommended)** | trycua/cua sandbox + NVIDIA OpenShell + our own agent loop; model via LiteLLM; DefenseClaw agent-gateway route; fully self-hosted, fits 8 GB, about 1–2 days more glue in P4.6 |
| E | other agents (OpenHands; nightly-labs/openbot, already rejected in D13) |

Recommendation: D for P4.6, optionally a one-week trial of A with a throwaway account and non-personal tasks.
If D is picked, D13 changes to "cua + OpenShell" and risk R11 closes.

Nothing for OpenBot is deployed. The Dell runs the alerting path and must stay light (decision 0009).
