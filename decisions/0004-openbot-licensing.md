# 0004: OpenBot licensing path on Linux (plan P4.1, risk R11)

- Date: 2026-11-15
- Status: proposed
- Decision: **pending (user)**

## Context

D13 picked **CopilotKit/OpenBot** for "an agent with its own sandboxed computer" on Omarchy. The plan
(architecture §"OpenBot (CopilotKit)", P4.6) has these parts:

- OpenBot's supervisor creates one computer per bot (a container with Chromium, `/workspace` and bash), using
  `COMPUTER_RUNTIME=runsc` (gVisor).
- An egress proxy with a per-bot allowlist, plus the policy gateway and audit log.
- `OPENAI_BASE_URL` points at LiteLLM.
- DefenseClaw's agent-gateway route is called from OpenBot's policy gateway.
- One computer at a time.

Omarchy is a Dell Inspiron 7348: i5-5200U (2 cores, 4 threads), 8 GB RAM (7.7 GiB usable), a 5400 rpm HDD, amd64,
Arch Linux. Risk R11 says OpenBot needs **CopilotKit Intelligence**, and that on Linux that means CopilotKit's managed
service or a licensed self-hosted install. This proposal checks that against primary sources (read 2026-11-15).

### What OpenBot is today

- [CopilotKit/OpenBot](https://github.com/CopilotKit/OpenBot): "open-source AI coworkers that each get a computer of
  their own".
  - Created 2026-08-17. v1.0.3 came out on 2026-11-14 and v1.0.2 on 2026-11-11, so it is very young and changes fast.
  - TypeScript, Bun 1.4+.
- **License: MIT** for the OpenBot app ([LICENSE](https://github.com/CopilotKit/OpenBot/blob/main/LICENSE)).
  - The [README](https://github.com/CopilotKit/OpenBot/blob/main/README.md) says it "uses **CopilotKit Intelligence**,
    which is separately licensed and can run entirely on your own machine or infrastructure".
- It has three parts ([README](https://github.com/CopilotKit/OpenBot/blob/main/README.md),
  [docs/architecture.md](https://github.com/CopilotKit/OpenBot/blob/main/docs/architecture.md)):
  - **Frontends:** desktop apps for macOS and Windows only, plus web, mobile, Slack and Teams.
  - **Backend:** the workspace API server, the supervisor (which holds the Docker socket) and the agent-computer
    containers, the gateway (the "action boundary"; it fails closed), the egress filter (`allow_all`,
    `defaults_plus_allowlist`, `allowlist_only`, `deny_all`), audit rows, live screen and take-over, and Postgres.
  - **CopilotKit Intelligence.**
- The plan's architecture matches what the docs describe; only the licensing and Linux story is different.

### What needs Intelligence, and what it costs

- **The OpenBot server won't start without Intelligence.** "The server starts only with a CopilotKit license or an
  Intelligence project key" ([docs/configuration.md](https://github.com/CopilotKit/OpenBot/blob/main/docs/configuration.md)).
  It needs `INTELLIGENCE_API_URL`, `INTELLIGENCE_GATEWAY_WS_URL` and `CPK_INTELLIGENCE_API_KEY`, and it refuses to
  start with an invalid or expired `COPILOTKIT_LICENSE_TOKEN`. No offline or mock mode is documented.
- **Intelligence** is closed and separately licensed. It provides durable threads (AG-UI streams), user memory,
  Automatic Learning, channels and analytics. It comes as **Managed**, **Self-hosted** (Helm or ECS) or **Local**
  (a preview) ([docs.copilotkit.ai/intelligence](https://docs.copilotkit.ai/intelligence)).
- **Pricing** ([copilotkit.ai/pricing](https://www.copilotkit.ai/pricing)):
  - Free hosted: 1,000 interactions per organisation per month.
  - Free self-hosted **Developer Edition**: "free for non-production use with a renewable 30-day license".
  - Self-hosted pay as you go: **$49 per month** for 10,000 interactions, and the deployment must be internet-connected
    to report usage.
  - Annual: custom pricing, and the only plan with offline or air-gapped installs.
- **OpenBot itself** ([open.bot/pricing](https://open.bot/pricing)) is "free for personal projects". OpenBot for
  Business costs up to $29 per active user per month. A personal home lab fits the free plan, so **the licence itself
  isn't the blocker.**
- **Local Intelligence is the blocker**
  ([Evaluate Intelligence locally](https://docs.copilotkit.ai/intelligence/self-hosting-local)):
  - It is "a preview supported on macOS with Docker Desktop".
  - "The CLI also accepts Linux with rootful Docker Engine, but Linux runtime evaluation has not been verified and is
    outside the supported preview scope."
  - It needs **at least 4 CPUs, 12 GiB RAM and 40 GiB free storage per stack**, and the CLI checks this.
- The Kubernetes (Helm) path needs amd64 nodes and a trial or production license (README).
- So R11 is confirmed. One correction: there is also a **free** managed tier.

### Can it run self-hosted on Linux with LiteLLM?

- **Model:** yes. `OPENAI_BASE_URL` sends "the whole deployment" to any OpenAI-compatible endpoint.
  - `BOT_MODEL` is passed through unchanged.
  - `COPILOTKIT_OPENAI_API=chat` selects Chat Completions instead of Responses.
  - The model must support tool calling ([configuration.md](https://github.com/CopilotKit/OpenBot/blob/main/docs/configuration.md)).
  - LiteLLM isn't named, but it fits. Its `smart`/`coder` aliases support tools.
- **Telemetry:** server telemetry is off by default. `DO_NOT_TRACK=1` / `COPILOTKIT_TELEMETRY_DISABLED=1` turn it off
  everywhere ([docs/TELEMETRY.md](https://github.com/CopilotKit/OpenBot/blob/main/docs/TELEMETRY.md)).
- **Linux host:** not a documented target. The development docs cover macOS and Ubuntu in WSL 2
  ([docs/development.md](https://github.com/CopilotKit/OpenBot/blob/main/docs/development.md)). A plain-Linux source
  install is likely to work, but that is our inference; the docs don't verify it.
- **Fully self-hosted on Omarchy:** not possible. The only self-hosted Intelligence that fits a home lab is the local
  preview, and it is macOS-only and needs 12 GiB RAM.

### Hardware

- One bot computer measures 409–548 MB. The docs give **2 GB minimum / 4 GB recommended, 1–2 vCPU**, a 1.4 GB image,
  and about 1 GB more per concurrent browser
  ([docs/deployment.md](https://github.com/CopilotKit/OpenBot/blob/main/docs/deployment.md)).
- The images are published for **linux/amd64 and linux/arm64**, so "amd64-only" applies to the Helm evaluation path,
  not the images.
- On Omarchy, the OpenBot server, Postgres and one computer would fit in about 3–4 GB next to the desktop. Adding local
  Intelligence (12 GiB) does not fit.

## Options

| Option | What it is | Cost | What it enables | Problems |
|---|---|---|---|---|
| **A. OpenBot + managed Intelligence (free hosted tier)** | OpenBot server, supervisor and computers on Omarchy; threads, memory and the realtime gateway in CopilotKit's cloud | $0 up to 1,000 interactions/month | The full D13 feature set: computers, gVisor, egress allowlist, audit, live view and take-over, memory | Conversation content and memory leave the home lab (a cloud dependency for a home agent); Linux host unverified; very new project (v1.0.x) |
| **B. OpenBot + local Intelligence (Developer Edition)** | Everything at home | $0 (renewable 30-day non-production licence) | Like A, with data at home | Mac-only preview; Linux unverified; needs 4 CPU / 12 GiB / 40 GiB; **doesn't fit Omarchy**; the Sparks are arm64 and Linux, so it is unsupported there too; licence renewal needs internet |
| **C. OpenBot + self-hosted Intelligence (pay as you go or Annual)** | Helm on amd64 Kubernetes nodes | $49+/month (PAYG must report usage online); Annual is custom | Supported self-hosting | Needs amd64 nodes with far more RAM than Omarchy has; paid; more than a home lab needs |
| **D. Fallback: trycua/cua + NVIDIA OpenShell + our own agent loop** | cua's Linux sandbox (`cua sb create ubuntu`, a gVisor container) or its `ghcr.io/trycua/linux` desktop image and cua-driver for computer use; OpenShell for the sandbox's file, network and process policy and credential injection; model via LiteLLM; DefenseClaw agent-gateway route; audit in DefenseClaw and Loki | $0. [cua](https://github.com/trycua/cua) is MIT (the Spaces app is FSL-1.1-MIT and not needed); [OpenShell](https://github.com/NVIDIA/OpenShell) is Apache-2.0 | Fully self-hosted on Linux, fits 8 GB with one computer, no licence keys, and the same security goals (one computer per bot, gVisor, egress allowlist, DefenseClaw on every action) | More of our own glue: no ready supervisor UI, live take-over is cua's VNC viewer rather than OpenBot's, and no thread memory unless we add it |
| E. Other agents (noted, not proposed) | [OpenHands](https://github.com/OpenHands/OpenHands) (MIT, one Docker container per conversation; computer use not checked); [nightly-labs/openbot](https://github.com/nightly-labs/openbot) (PolyForm Noncommercial 1.0.0, Arch/Omarchy AppImage, computer use via cua-driver) | $0 for personal use | A quicker agent UI | nightly-labs/openbot runs agents with full access and says it is "not a security boundary"; it was already rejected in D13 |

## Recommendation

1. **Go with D (cua + OpenShell) as the P4.6 build.** It is the only option that runs fully self-hosted on Omarchy
   without a licence key or a cloud dependency. It keeps every security goal of D13, and the plan already names it as
   the fallback.
2. **Optional, time-boxed: try A** (OpenBot on the free hosted tier) for at most a week, with a throwaway CopilotKit
   account and non-personal tasks only. This tells us whether OpenBot's UI and take-over are worth a cloud dependency.
3. **Revisit B** when CopilotKit supports local Intelligence on Linux with a smaller footprint, or when an amd64 host
   with 16 GB or more joins the fleet.

If the user picks D, D13 changes from "CopilotKit/OpenBot" to "cua + OpenShell" and P4.6 is reworded. R11 then closes.
If the user picks A, record what data goes to CopilotKit in `docs/architecture.md` and give OpenBot's LiteLLM key
its own budget.

## Decision

**Pending (user).**

## Consequences

- D: about 1–2 days more work in P4.6 for the glue (a small supervisor around cua sandboxes, the OpenShell policy,
  audit to DefenseClaw and Loki). There are no recurring costs and no outside service.
- A: little glue, but threads and memory are stored by CopilotKit. The free tier's 1,000 interactions a month is enough
  for light use. The supported setups are macOS and Windows, so Linux problems would be ours to solve.
