---
title: Docs site (docs.nghodki.ai)
description: These pages, built from main every 15 minutes on the Dell and signed in at the front door (edge-auth, Pocket ID).
---

The site you are reading. Private: only the home front door serves it, behind Pocket ID (group `admins`), on the LAN
and Tailscale. Never GitHub Pages. Full procedure: `runbooks/docs-site.md`.

| | |
|---|---|
| URL | `https://docs.nghodki.ai` (http → https) |
| Source | `docs-site/` (MkDocs Material: `mkdocs.yml`, `content/docs/`, `hooks/mermaid.py`, `requirements-docs.txt`) |
| CI | `pr-checks.yml` job `docs`: `mkdocs build --strict` fails a PR on a broken link, anchor or nav entry |
| Build | role `docs_site` on the Dell (`playbooks/ops.yml`): `docs-build.timer` every 15 min and at boot; only when `main` moved and `docs-site/` changed; pinned Python image by digest, hash-locked requirements |
| Fetch | read-only deploy key `docs-dell` (`secrets/docs.enc.yaml` → `docs_deploy_key`, root-only on the Dell), shallow sparse clone of `docs-site/` |
| Files | `/srv/docs/current` → `releases/<docs tree hash>/`, swapped atomically; the last 5 releases kept for rollback |
| Containers | ops stack: `docs` (Caddy 2.11.9, read-only) on 192.168.86.49:4181, which answers only requests with the front door's `X-Edge-Origin` token (else 403; `/healthz` open); `:8080` on the stack network for Homepage. The same Caddy is Homepage's gate (:4180) |
| Sign-in | the front door: `import signed_in 192.168.86.49:4181 admins` (client `edge-auth`; one session with Homepage, Gatus and MLflow); `edge_origin_token` in `secrets/console.enc.yaml` |
| Health | Gatus `docs.nghodki.ai` (302 to Pocket ID) and `docs build` (external endpoint: build result, 1 h heartbeat); journal tag `docs-build` in Loki |

Measured on 2026-11-15: PR #82 merged at 03:08:54Z and was live at 03:15:55Z (7 min: the wait for the next
quarter-hour timer run, then about 50 s to clone, install and build). Worst case is about 16 min.

A failed build leaves the last good site up. Nothing on the site loads from other hosts (system fonts, local search,
Mermaid served from the site).

Until 2026-11-15 the docs had their own oauth2-proxy and Pocket ID client (`docs`); now the front door's one sign-in
covers them ([decision 0011](https://github.com/nikghodki/homelab/blob/main/decisions/0011-one-sign-in-proxy.md)).
