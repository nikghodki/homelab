# 0009: No dedicated services box for now

Date: 2026-11-15. Decided by: nikghodki.

**Context:** today both Sparks crashed from GPU/unified-memory exhaustion (DGXMM's two-Spark model work), taking every
service with them. A small dedicated x86 box (32–64 GB RAM, NVMe) was proposed to host k3s' control plane and all
non-GPU services, so the Sparks would carry only models and sims. The Dell (Omarchy) can't take that role: 8 GB max
(one SO-DIMM slot), 2 cores, a 5400 rpm hard drive, Wi-Fi only.

**Decision:** no services box for now. Services stay on the Sparks, apart from the alerting path, which is on the
Dell (Gatus, ntfy, Homepage; PR #55).

**Consequences:**
- The Sparks keep running services (~8–10 GB each, measured 2026-11-15) next to models. Model work must leave that
  room: a hard reserve per Spark (plan P2.7: dgx-1 ≥ 8 GiB free, dgx-2 15–23 GiB for services), enforced by DGXMM and
  by memory limits on our own jobs (AIBOM capped at ~6 GiB with a low-memory guard; sim jobs ≤ 16 GiB).
- A GPU OOM can still take a Spark's services down. Alerting survives on the Dell, with a dead-man path for the
  Dell itself.
- k3s keeps dgx-1, dgx-2 and the Jetson as its three etcd members; P3.7 moves services into the cluster on the
  Sparks (the Dell takes small stateless pods).
- Revisit if the Sparks crash again from model work, or if services outgrow the reserve.
