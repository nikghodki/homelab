# 0001: GitHub Free for nikghodki/homelab (plan P1.9)

Date: 2026-11-15. Decided by: nikghodki.

**Decision:** stay on the free personal plan. No GitHub Pro.

**Consequences:**
- Branch protection with *required* status checks isn't enforced on a private repo. The merge rule stays procedural:
  merge only when `gh pr checks <n> --watch` exits 0. Every merge so far has followed it.
- Actions minutes are limited. Long jobs (red-team, simulation evals) go to the self-hosted runner on dgx-2 (plan P4.8).
- Revisit if a merge with failing checks ever happens, or if minutes run out.
