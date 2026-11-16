---
title: PR, merge and identity rules
description: How changes get in (decision 0001), the identity rules, the no-code-on-the-laptop rule, and how people and agents work in parallel with worktrees.
---

## Merge only on green (decision 0001)

The repo is private on GitHub Free, so branch protection with **required** checks isn't enforced. The rule is
procedural and has held for every merge:

```bash
gh pr create --fill                       # from your branch, on dgx-1
gh pr checks <n> --watch                  # wait; must exit 0
gh pr merge <n> --squash --delete-branch  # squash-only repo
```

Never merge red. Revisit (GitHub Pro, $4/month) if a red merge ever happens or Actions minutes run out.

## Identity

- Commits and pushes only as `nikghodki <92228606+nikghodki@users.noreply.github.com>`. Check before committing:
  `git config user.name; git config user.email`.
- **No `Co-Authored-By` or any other trailers** in commit messages.
- `gh` on dgx-1 (`~/.local/bin/gh`) is logged in as nikghodki. **Never** use the admin laptop's `gh` or `git`: they are a
  work account.
- Only nikghodki commits and pushes to this repo (top-level README "Rules").

## No code on the laptop

The admin laptop is a work machine. Nothing is written, built or run there: no scripts, no checkouts, no temp files.
Everything happens on dgx-1, over SSH (heredocs are fine: `ssh -p 2244 nikghodki-dgx@localhost 'bash -s' <<'EOF' ... EOF`).

## Read-only by default on hosts

When investigating, use commands that change nothing (`docker ps`, `systemctl status`, `ss`, `kubectl get`, reading
files). Restarts, edits and deploys are separate, deliberate steps with `--check --diff` first.

## Don't touch other projects

DGXMM, LiteLLM, model engines and the GPUs belong to the DGXMM session. Read their documented state; don't change them
from fleet work.

## Working in parallel (people and agents)

Several sessions work at once (for example P3.3 edge-in-cluster and P3.5 Enforce while these docs were first written). Each
uses its **own git worktree** and branch:

```bash
cd ~/homelab && git fetch -q
git worktree add ~/homelab-wt/<topic> -b <branch> origin/main
cd ~/homelab-wt/<topic>
# ... work, commit ...
git fetch -q && git rebase origin/main      # before pushing and again before merging
git push -u origin <branch>
# after the merge
cd ~/homelab && git worktree remove ~/homelab-wt/<topic>
```

Rules for parallel work:

1. Stay inside your area; don't edit another session's files (for example `docs/project-plan.md` is updated by the
   session that finishes a plan item).
2. Rebase before pushing and before merging; resolve conflicts on your side.
3. Before deploying a **shared** stack (`observe` above all), rebase and deploy from an up-to-date tree:
   `remove_orphans` would otherwise remove another session's services.
4. Argo CD apps can be tested from a branch (`targetRevision: <branch>`), as P3.3 did before #72 merged, but `main`
   must end up as the source.
5. Don't leave worktrees behind (`git worktree list`).

## What a PR should contain

- The change, and the docs/runbook update if behaviour changed (these docs live in `docs-site/`).
- Secrets only as SOPS changes. CI must stay green: yamllint, gitleaks, Trivy, the scanners.
- A short "what and why"; for robot changes, whether safety limits changed.
- For changes outside the repo (front door, DNS): what you changed by hand on which host.
