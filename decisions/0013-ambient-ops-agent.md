# 0013: Ambient ops agent: approved design, answers to its 15 questions, shadow mode first

- Date: 2026-11-16
- Status: decided (nikghodki: "looks good, go ahead" on the draft design, PR #114)

## Context

[docs/ambient-agent-design.md](../docs/ambient-agent-design.md) proposes an agent that watches every alert, check,
sync, CI run and log baseline in the fleet, investigates with read-only tools and the local model, writes RCAs and
notifies, with a portal at `ops-agent.nghodki.ai`. It left 15 decisions open (§13). This records the answers and the
order of the build.

## Decision

Build the design's phases up to and including **S1 shadow mode** (A0 prerequisites, A1 shadow investigator, the
read-only part of the portal). In shadow mode the agent has **no write action anywhere**: no GitHub write, no live
action, no silences, no PRs. It watches, investigates, writes RCAs into its own database, and notifies on its own ntfy
topic. Promotion past S1 (PRs, live actions) waits for your review after the shadow period.

| # | Question | Decided |
|---|---|---|
| Q1 | GitHub identity | A fine-grained PAT of nikghodki, held only by the Git broker. **Not created yet**: in shadow mode the agent has no GitHub write access. Reading the repo uses a read-only deploy key (the docs-dell pattern). Reading Actions runs of this private repo needs a token: a second fine-grained PAT that is **read-only** (Actions, Contents, Pull requests, Metadata: read); until you create it, the GitHub poller stays off |
| Q2 | Auto-merge classes | None |
| Q3 | Live actions, Ansible | No live actions yet. Later: CI reruns (infra failures) and pod restarts on "Ask". Ansible: `--check` only |
| Q4 | Portal | Standalone `ops-agent.nghodki.ai` |
| Q5 | Investigation engine | **Own loop** (A1 head-to-head, 2026-11-17, design §11.5): on qwen3.8-27b HolmesGPT was not more accurate, used 3x the tokens, timed out once and denied a real outage (G1) |
| Q6 | Fallback when the model is down | Fixed (deterministic) queries only; no cloud model |
| Q7 | Keep `qwen3.8-27b` warm | No, not for now (the first look hides the cold start) |
| Q8 | The Dell and the Pi | Read-only on both. No e-stop access of any kind |
| Q9 | ntfy buttons | `view` (open the portal) plus `http` Deny/Snooze; never Approve |
| Q10 | Quiet hours, family impact | 22:30-07:30; Home Assistant, Open WebUI, DNS and the front door always notify |
| Q11 | Incident memory | Postmortem PRs later; in shadow mode postmortems go to the agent's own database |
| Q12 | Temporal mTLS | Required before the agent runs on Temporal; done first |
| Q13 | Budget, concurrency | 1 M tokens/day, 2 investigations at once |
| Q14 | Renovate and CI triage | Comments and reruns later; in shadow mode only reports |
| Q15 | Chat | Read-only plus proposals |

## Alternatives considered

The options per question are in the design's §13; the recommendations were taken except Q7 (stay on demand), Q11
(database only for now) and Q14 (reports only while in shadow mode).

## Consequences

- Temporal's frontend gets mTLS and per-namespace authorization before any agent workflow runs (A0); every existing
  Temporal client is moved to a client certificate.
- The agent's credentials in shadow mode are read-only: a Kubernetes reader without Secrets or exec, a Grafana Viewer,
  an Argo CD read-only account, an SSH user per host limited to an allowlist of read commands (forced command), a
  LiteLLM key for `qwen3.8-27b` only with a budget, a publish-only ntfy token for topic `ops-agent`.
- The existing alert path (Alertmanager and Gatus to ntfy `fleet-alerts`) is unchanged; the agent's receiver is an
  extra route with `continue: true`.
- The fine-grained PAT (Q1) is created by you only when phase A3 (PRs) starts, after the shadow review.

## As built (2026-11-17)

S1 shadow mode is live (design §15, runbooks/ops-agent.md). Replay A0: own loop 1 yes / 4 partly / 2 no on the seven
gold incidents, claim precision 0.90, no unsafe proposal, no secret in stored output. The repo turned out to be public,
so the read-only PAT of Q1 isn't needed for CI polling while it stays public.
