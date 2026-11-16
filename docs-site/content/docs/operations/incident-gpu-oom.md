---
title: Incident 2026-11-15, both Sparks down from GPU memory exhaustion
description: Timeline, impact, causes and follow-ups of the unified-memory OOM that took dgx-1 and dgx-2 down on 2026-11-15.
---

## Summary

On 2026-11-15, model-engine and NCCL test work (the DGXMM session's two-Spark model work) exhausted the GB10 unified
memory on both Sparks. The NVIDIA driver logged out-of-memory errors, the kernel's OOM killer fired, and both machines
went down and had to be hard-reset. While they were down, Gatus and ntfy (then on dgx-2) were down too, so **no alert
reached the phone**. The fleet changed afterwards: alerting moved to the Dell, a dead man was added for the Dell, our
own jobs got memory caps, and memory guards appeared on both Sparks.

## Timeline (PST, from the kernel journals and the repo)

| Time | Event |
|---|---|
| 2026-11-14 22:44 | dgx-2: first `NVRM ... Out of memory [NV_ERR_NO_MEMORY]` in the kernel log (the boot survived) |
| 2026-11-15 14:41:27 | dgx-2: `NVRM ... Out of memory` again (`_memdescAllocInternal`, `system_mem.c`) |
| 14:46:14 – 14:46:22 | dgx-1: ten `NVRM ... Out of memory` lines |
| 14:49:03 | dgx-1: system OOM killer (invoked by `redis-server`) kills a Chrome process |
| 14:49:50 | dgx-1: journald "Under memory pressure, flushing caches" |
| 14:51:28 | dgx-1: OOM killer invoked by `ansible-lint`; the journal ends here |
| 14:59:10 | dgx-1 boots again |
| 15:00:48 | dgx-2: kernel `Tainted: [D]=DIE`; the journal ends |
| 15:02:59 | dgx-2 boots again |
| 15:16:53 | dgx-1: `gpu-oom-guard.service` starts ("kill largest GPU user below 6144 MiB available") |
| 15:19:35 | dgx-1: gpu-oom-guard kills a python3 process holding about 104 GiB of GPU memory (MemAvailable was 5.1 GiB) |
| 15:43 | PR #54 (k3s) merged; decision 0005 records the crash and why the Jetson's etcd vote matters |
| 16:22 | PR #55: Gatus, ntfy and Homepage move to the Dell; the Dell never sleeps |
| 16:48 | PR #57 / decision 0006: the platform budget is kept small because of the OOMs |
| 17:05 | PR #61 / decision 0009: no dedicated services box for now; services stay on the Sparks with a hard reserve |
| 17:06 | PR #60: AIBOM memory cap 6G and low-memory guard on the Sparks; dead man for the Dell; human-only e-stop reset |

Decision 0006 speaks of "two GPU/unified-memory OOMs"; the journals show two NVRM OOM episodes on dgx-2 (22:44 on
11-14 and 14:41 on 11-15) and one on dgx-1. The Sparks also rebooted on 2026-11-14 around 17:35 (dgx-2) and 18:27–18:49
(dgx-1); those causes were not checked.

## Impact

- All services on both Sparks down for about 10–15 minutes: front door, DNS, LiteLLM, Open WebUI, NATS, Fleet, observe
  stack, Pocket ID, Temporal, MLflow.
- No alerts: Gatus and ntfy were on dgx-2.
- The k3s cluster was not built yet at the time (PR #54 merged at 15:43), so no quorum loss.
- The robot was unaffected (local safety loop; it wasn't driving).

## Causes

- GB10 memory is unified: GPU allocations come out of the same 121 GiB as every service, and container memory limits
  don't cover CUDA allocations.
- No reserve was enforced (P2.7 is pending in DGXMM), and no guard killed a runaway GPU process.
- Alerting lived on one of the machines that failed.

## Follow-ups

| Action | Status |
|---|---|
| Alerting on the Dell, dead man via ntfy.sh | done (#55, #60) |
| AIBOM capped at 6G on the Sparks, skip image scans under 20 GiB free | done (#60) |
| Sim jobs capped (16 GiB cgroup, JAX 15%, `measure.sh` watchdog at 8 GiB) | done (#48) |
| Platform pods kept small; Kyverno first with failurePolicy Ignore (#57), then 2 admission replicas, one per Spark, before Enforce (#65) | done |
| `earlyoom` and `gpu-oom-guard` on both Sparks | live, **not in the repo** (the unit names a role `memory_guard` that doesn't exist on any branch); bring it into Git |
| DGXMM memory reserves (P2.7) | pending (DGXMM session) |
| Revisit a services box if it happens again | decision 0009 |
