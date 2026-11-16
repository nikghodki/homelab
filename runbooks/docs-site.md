# Docs site: https://docs.nghodki.ai (private)

The operator docs in `docs-site/` are built with MkDocs Material and served **only** from the Dell (Omarchy), behind
the front door's sign-in (`edge-auth`, Pocket ID group `admins`; [sign-in.md](sign-in.md)). They stay readable when both Sparks are down, as long as the front door
and Pocket ID are up (see [Limits](#limits)). Never GitHub Pages: the repo is private and nothing is published to the
internet.

| | Where |
|---|---|
| Source | `docs-site/content/docs/*.md`, navigation in `docs-site/mkdocs.yml` (`nav:`), Mermaid hook `docs-site/hooks/mermaid.py` |
| Build tools | `docs-site/requirements-docs.txt` (MkDocs 1.6.1, Material 9.7.7, pymdown-extensions 12.3; pinned with hashes, same as DGXMM) |
| CI | `pr-checks.yml` job `docs`: `mkdocs build --strict` (broken links, anchors or nav entries fail the PR) |
| Build on the Dell | role `docs_site` (`playbooks/ops.yml`): `docs-build.timer` (every 15 min and 2 min after boot) → `/usr/local/sbin/docs-build` |
| Served files | `/srv/docs/current` → `releases/<docs tree hash>/` (the newest 5 are kept) |
| Web server | `docs` (Caddy, read-only) in the ops stack (`hosts/stacks/ops`): `192.168.86.49:4181` (LAN only) answers only with the front door's `X-Edge-Origin` token (else 403; `/healthz` open), `:8080` on the stack network for Homepage. The same Caddy gates Homepage on `:4180` |
| Sign-in | Pocket ID client `docs` (`identity/pocket-id.yaml`, PKCE S256, `allowed_groups = admins`); `oidc_docs_secret` and `oauth2_proxy_docs_cookie_secret` in `secrets/console.enc.yaml` |
| Front door | in-cluster Caddy (`cluster/platform/edge/caddy/Caddyfile`, `@docs`; name `docs` in `cluster/platform/edge/names.txt`); the same block in dgx-1's `~/edge-gateway` for rollback |
| Secrets | `secrets/docs.enc.yaml`: `docs_deploy_key` (read-only deploy key `docs-dell`), `docs_build_gatus_token` |
| Monitoring | Gatus `docs.nghodki.ai` (302 to Pocket ID) and external endpoint `docs build` (key `docs_docs-build`); journal tag `docs-build` in Loki |

## How it's built

`docs-build` runs as root on the Dell (it needs the deploy key and Docker):

1. `git ls-remote` of `main` with the deploy key (`/etc/homelab/docs/`, root only, github.com's host key pinned). If
   `main` is the commit it saw last time, nothing is built; it only repeats the last result to Gatus.
2. Otherwise a shallow, blobless, sparse clone of `docs-site/` only. If the `docs-site/` tree hash is the one being
   served, it records the commit and stops ("docs-site unchanged").
3. Build in `python:3.12.16-slim-trixie` (by digest, `docs_site_build_image`) as user `docsbuild`, read-only root,
   no capabilities, source mounted read-only: `pip install --require-hashes --only-binary=:all:` then
   `mkdocs build --strict` into `/srv/docs/releases/.new-<tree>`. pip wheels and Mermaid are cached in
   `/var/lib/docs-build/cache`. Mermaid 11.17.2 comes from the npm registry tarball, checked against its SHA-512
   integrity, and is served by the site itself (no CDN at runtime).
4. On success: rename to `releases/<tree>`, then point a new symlink at it and rename it over `current` (atomic;
   readers get the old or the new site, never half). Old releases beyond 5 are removed.
5. On failure: the new folder is deleted, `current` is untouched (the last good site stays up).

Every run that does something logs one line with tag `docs-build` (`OK: built main <sha> ...`,
`main <sha>: docs-site unchanged ...`, `FAILED: ... (still serving releases/<tree>)`); git, pip and mkdocs output is
tagged `docs-build-job`. Both reach Loki through the Dell's collector (journald).

```bash
# on the Dell
systemctl list-timers docs-build.timer
journalctl -t docs-build -t docs-build-job --since today
sudo cat /var/lib/docs-build/state            # seen=<commit>, result=ok|failed
readlink /srv/docs/current; cat /srv/docs/current/build-info.txt
```

Grafana Explore (Loki):
`{host_name=~".+"} |= "docs-build" | json syslog="SYSLOG_IDENTIFIER", msg="MESSAGE" | syslog="docs-build" | line_format "{{.msg}}"`.

## Alerts

- **`docs build`** (Gatus external endpoint, group `docs`): the build posts `success=true|false` after every run.
  A failing `main` stays red (one ntfy alert) until a fixed commit builds. No post for 1 h (timer stopped, GitHub
  unreachable, Docker broken) is also a failure. This runs entirely on the Dell, so it works without the Sparks; a
  Loki/vmalert rule would not (both are on dgx-2).
- **`docs.nghodki.ai`** (group `web`): through the front door VIP; signed out it must answer 302 (to Pocket ID).

## Updating the docs

Change the pages in a PR (the `docs` CI job must pass), gated merge. Within 15 minutes of the merge the timer builds
the new `main` and the site shows it (`build-info.txt` names the commit). To publish at once:

```bash
ssh nikghodki@192.168.86.49 sudo systemctl start docs-build    # from dgx-1
```

Force a rebuild of the same commit: `sudo rm /var/lib/docs-build/state && sudo systemctl start docs-build`.

## Adding a page

1. Create `docs-site/content/docs/<section>/<page>.md` with frontmatter:

   ```markdown
   ---
   title: Page title
   description: One sentence; shown in search results and the HTML description.
   ---
   ```

   No H1 in the body (the title is the H1).
2. Add it to `nav:` in `docs-site/mkdocs.yml`, in the section's list. A page that isn't in `nav:` fails the strict
   build.
3. Link pages with relative `.md` paths (`../network/ports.md`, `ports.md#anchor`); they work on github.com and the
   site, and the strict build checks every link and anchor. Repo files are named in backticks, not linked.
4. Available: admonitions (`!!! note`), tabs (`=== "Tab"`), `??? details`, code blocks with a copy button,
   ```` ```mermaid ```` diagrams, tables, footnotes. Python-Markdown is stricter than GitHub: put a blank line before a
   list and indent nested lists and blocks inside list items by 4 spaces.
5. Check locally on dgx-1 before pushing:

   ```bash
   python3 -m venv ~/.venvs/docs && ~/.venvs/docs/bin/pip install --require-hashes -r docs-site/requirements-docs.txt
   NO_MKDOCS_2_WARNING=1 ~/.venvs/docs/bin/mkdocs build --strict -f docs-site/mkdocs.yml -d /tmp/docs-site
   NO_MKDOCS_2_WARNING=1 ~/.venvs/docs/bin/mkdocs serve -f docs-site/mkdocs.yml -a 127.0.0.1:8001   # ssh -L to view
   ```

6. Add the page to the coverage checklist in `docs-site/README.md` if it covers a new role, playbook, stack, runbook
   or decision.

## Rolling back

The site: point `current` at an earlier release (they are named by `docs-site/` tree hash; `build-info.txt` in each
names the commit):

```bash
# on the Dell
ls -lt /srv/docs/releases/
sudo ln -sfn releases/<tree> /srv/docs/.current.new && sudo mv -T /srv/docs/.current.new /srv/docs/current
```

It stays until `main` changes again; then revert the bad docs commit in a PR instead.

The hosting: remove the `@docs` route from the front door's Caddyfile (PR), or
`docker compose --project-directory /opt/homelab/ops stop docs` (that also takes Homepage's gate down). The timer: `sudo systemctl disable --now
docs-build.timer`. The deploy key: `gh repo deploy-key list -R nikghodki/homelab`, then `gh repo deploy-key delete
<id>`.

## Rotating

- Deploy key: `ssh-keygen -t ed25519 -N "" -f /dev/shm/k`, `gh repo deploy-key add /dev/shm/k.pub --title docs-dell`
  (read-only: no `--allow-write`), store the private key as `docs_deploy_key` with `sops set --value-stdin
  secrets/docs.enc.yaml '["docs_deploy_key"]'` (JSON string on stdin), delete the old key, `shred -u` the files,
  rerun `playbooks/ops.yml`.
- Gatus token: new value in `secrets/docs.enc.yaml`, then `playbooks/alerting.yml` and `playbooks/ops.yml`.
- Sign-in: the shared `edge-auth` secrets and the edge origin token (`runbooks/sign-in.md`, "Rotate"); the token also
  needs `playbooks/ops.yml`.

## Limits

- Sign-in needs Pocket ID (dgx-2) and the front door (k3s Caddy on the Sparks). With both Sparks down the site is
  still on the Dell, but not reachable by name. Break glass, from a machine that can SSH to the Dell:

  ```bash
  ssh -L 8090:127.0.0.1:8090 nikghodki@192.168.86.49 'python3 -m http.server -d /srv/docs/current -b 127.0.0.1 8090'
  # then open http://127.0.0.1:8090/ locally; Ctrl-C stops it
  ```

- `requirements-docs.txt` and the Python image aren't updated by Renovate; bump them by hand with DGXMM's versions
  (the regenerate command is in the file's header).
