---
title: Docs site (docs.nghodki.ai)
description: These pages, built from main every 15 minutes on the Dell and served behind oauth2-proxy and Pocket ID.
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
| Containers | ops stack: `docs` (Caddy 2.11.9, read-only, no ports) and `oauth2-proxy-docs` (7.15.6) on 192.168.86.49:4181 |
| Sign-in | Pocket ID client `docs`, PKCE S256, `allowed_groups = ["admins"]`, cookie `_docs_oauth2_proxy`; `secrets/console.enc.yaml` → `oidc_docs_secret`, `oauth2_proxy_docs_cookie_secret` |
| Health | Gatus `docs.nghodki.ai` (302 to Pocket ID) and `docs build` (external endpoint: build result, 1 h heartbeat); journal tag `docs-build` in Loki |

A failed build leaves the last good site up. Nothing on the site loads from other hosts (system fonts, local search,
Mermaid served from the site).

Why a second oauth2-proxy instead of a second upstream on the `ops` one: an oauth2-proxy instance signs in with one
OIDC client and one cookie domain, and the docs have their own client (`docs`), so they get their own small instance.
