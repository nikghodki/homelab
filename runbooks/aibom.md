# Cisco AIBOM (AI bill of materials)

[Cisco AIBOM](https://github.com/cisco-ai-defense/aibom) (`cisco-aibom`, PyPI) inventories the AI parts of code and
container images: models, agents, MCP servers and clients, skills, prompts, datasets, endpoints, AI dependencies,
secrets. Decision: decisions/0003-cisco-ai-defense-tools.md.

| Piece | Where | Managed by |
|---|---|---|
| Version pin (hash-locked, universal: x86_64 CI and aarch64 hosts, Python 3.12/3.13) | `.github/requirements-aibom.in` / `.txt` | Renovate (pip-compile) |
| CI scan of this repo, JSON as the `aibom` artifact (30 days) | `pr-checks.yml` job `aibom` (~1.5 min) | — |
| Nightly fleet scan | systemd `cisco-aibom.timer` (system unit, ~04:20; Jetson 01:30) on dgx-1, dgx-2, Jetson, Pi | role `cisco_aibom`, `playbooks/aibom.yml`, `host_vars/*` |
| Full reports | `/var/lib/cisco-aibom/<host>-<date>.json` on each host, root only, 30 days | the job |
| Summary and diff | journal (`SyslogIdentifier=cisco-aibom`) → host collector → Loki on dgx-2 | — |
| Dashboard | Grafana → Fleet → **AI inventory** | `hosts/stacks/observe/grafana/dashboards/fleet/ai-inventory.json` |

## What each host scans

| Host | Code dirs (read in place) | Container images (of the running containers) |
|---|---|---|
| dgx-1 | DGXMM `~/workspace/dgx-model-manager`, LiteLLM stack `/opt/homelab/litellm` | `litellm-proxy`, `open-webui` |
| dgx-2 | — | `observe-phoenix-1`; and the **Jetson's** Home Assistant image by digest (below) |
| jetson | Hermes `~nikjetson/.hermes/hermes-agent`, Hermes `~hermes-nikhil/.hermes/hermes-agent`, `~/workspace/roboclaw` | none here (`cisco_aibom_image_scans: false`); scanned on dgx-2 |
| pi | PicoClaw `/var/lib/picoclaw/.picoclaw` (config, workspace, skills) and its MCP server `/var/lib/picoclaw/roboclaw` (own user since 2026-11-15, runbooks/robot-safety.md), `~/workspace/roboclaw` | — |

### Another host's images, scanned on dgx-2

An image scan doesn't have to run where the image runs. The Jetson has ~3 GiB free, and one AIBOM run there took
~1.1 GiB (tool review 2026-11 §2.7), so it runs **code-dir scans only**: `cisco_aibom_image_scans: false` in
`host_vars/jetson.yml` makes the role refuse `cisco_aibom_containers` there. dgx-2 scans the Jetson's images instead:

```yaml
# host_vars/dgx-2.yml
cisco_aibom_remote_images:
  - host: jetson                 # reported as this host
    name: homeassistant          # target "image:homeassistant"
    image: <repo:tag@sha256:...> # read from hosts/stacks/home-assistant/compose.yaml: the digest the Jetson runs
    paths: [/usr/src/homeassistant]   # extra dirs for the docker-cp fallback
```

The job on dgx-2 pulls the digest if it isn't there (and removes images it pulled once they leave the list,
`/var/lib/cisco-aibom/remote-images.json`), scans it under dgx-2's memory guard (`image_min_mem_gib` 20,
per-image override by `name` in `cisco_aibom_image_min_mem_gib_by_container`), and writes and logs the result as the
Jetson's: `/var/lib/cisco-aibom/jetson-<date>.json` **on dgx-2**, journal lines with `"host": "jetson"` and
`"scanned_on": "dgx-2"`. The AI inventory dashboard groups by that `host` field (`fleet_host` becomes the JSON
`host`; `scanned_on` keeps the scanning host), so the Jetson's code (from the Jetson) and image (from dgx-2) add up
under `jetson`. Remote images must be pinned by digest (the role and the job both refuse a tag).

Not scanned remotely: `ros-zenoh` (built on the Jetson from a digest-pinned base, no registry digest, no AI
components). The Pi runs no containers.

Pocket ID and the rest of the observe stack are not AI components and are not scanned. To add a target, extend
`cisco_aibom_dirs` / `cisco_aibom_containers` in the host's `host_vars` and run the playbook.

## How it works

Per host, not centrally: AIBOM scans local paths and local images, so each host scans what it runs, secrets in
the scanned code never leave the host, and only counts and component names go to Loki (secret findings are counted,
never named). The job (`/opt/cisco-aibom/cisco-aibom-fleet`) runs `cisco-aibom analyze` once per target, writes one
JSON per host and night, compares it with the previous night and logs:

- `{"event": "aibom", "total", "counts" (per type), "targets" (per dir/image), "added", "removed", "errors", ...}`
- `{"event": "aibom.new" | "aibom.removed", "target", "type", "name", "file"}`, at most 50 per direction and night.
- `{"event": "aibom.skipped", "target", "reason": "skipped: low memory", "mem_available_gib", "need_gib"}` (memory guard, below).

A target that fails is reported in `errors` (the unit exits 1) and is not counted as "removed". A skipped target is
not an error (exit 0, listed in `skipped`), and each target is compared with its last real scan, so a skipped night
doesn't show its components as removed and then added again.

Containers use AIBOM's container mode (`--container-extraction-tier docker`: `docker save` to find the app dirs,
then create + cp). dgx-2's Docker uses the containerd image store, which drops compressed layers after unpacking,
so `docker save` fails there; the job then copies the image's working dir, `/app`, `/opt` and `/srv` out of a
created (never started) container and scans that folder (`"method": "docker-cp-fallback"` in the JSON).

The unit runs as root (to read every user's code and reach the Docker socket) but read-only: only
`CAP_DAC_READ_SEARCH`, `ProtectSystem=strict`, `ProtectHome=read-only`, its own `/tmp`, `Nice=19`, idle I/O
(`IOSchedulingClass=idle`), `MemoryMax` per host (Sparks 6G, `group_vars/sparks.yml`; Jetson 3G; Pi 1500M; default 4G)
and `OOMPolicy=continue` (a target killed at the cap is that target's error; the rest of the run goes on).

### Memory guard on the Sparks

A loaded model can use most of a Spark's unified (CPU+GPU) memory; both Sparks crashed from memory exhaustion on
2026-11-15, and the job used to be allowed 16G. Now:

- `MemoryMax=6G` for the whole job on dgx-1 and dgx-2.
- Before each **image** target, the job reads `MemAvailable` from `/proc/meminfo`. Under
  `cisco_aibom_image_min_mem_gib` (Sparks: 20; default 0 = off) the image is skipped and the job logs
  `aibom.skipped` / `skipped: low memory` to the journal (→ Loki). Per-container thresholds:
  `cisco_aibom_image_min_mem_gib_by_container: {open-webui: 40}`. Code dirs are always scanned (small, no Docker).
- Open WebUI fits in 6G, so it has no special threshold. Measured 2026-11-15 with the 6G cap: whole run 16 min,
  Open WebUI image (4.1 GB) the largest part; cgroup peak 5.3G including page cache, which the cap reclaims; anonymous
  memory peaked at 4.4 GiB. The old "13 GB" was not a hard need. If a later Open WebUI grows past 6G, the target
  fails alone (`OOMPolicy=continue`); then set `{open-webui: 40}` and raise `cisco_aibom_memory_max` only for that
  case, or drop the image and scan its app dirs (the docker-cp fallback is lighter).

```bash
# what tonight's guard would see / what it did
grep MemAvailable /proc/meminfo
sudo journalctl -t cisco-aibom --since today -o cat | grep -E '"aibom.skipped"|"event": "aibom"'
```
Each Hermes checkout on the Jetson is about 8,000 Python files and takes over an hour on the Orin, so the Jetson
starts at 01:30 with a 3 h limit per target.

```bash
# the Jetson's images, scanned on dgx-2
sudo journalctl -t cisco-aibom --since today -o cat | grep '"scanned_on"'
sudo ls /var/lib/cisco-aibom/jetson-*.json     # on dgx-2
```

**LLM (since 2026-11-15).** `cisco-aibom analyze` requires `--llm-model`; its agentic stage confirms or drops each
candidate and adds identifiers. The role writes `/etc/cisco-aibom/llm.env` (root 0600: `AIBOM_LLM_*`, read by
cisco-aibom itself so the key never shows in the process list) from the dedicated LiteLLM key `cisco-aibom`
(`qwen3.8-27b` only, 10 rpm, 1 in flight; `secrets/litellm.enc.yaml`, loaded by `playbooks/aibom.yml`), with
`AIBOM_LLM_REASONING=off`, 0.2 requests/s and a 900 s batch timeout (the first request may start the on-demand model).
dgx-1 uses `http://127.0.0.1:4000/v1`, the others `http://model.nghodki.ai/v1`. Without a key the job points it at a
closed port and falls back to its deterministic scanners (`agentic_status: degraded`), as before.

## Two AIBOMs on the Jetson

| | DefenseClaw AIBOM (role `defenseclaw_aibom`) | Cisco AIBOM (role `cisco_aibom`) |
|---|---|---|
| Question | What has this agent **connected**? | What do the **code and images** contain? |
| Source | `defenseclaw aibom scan --json`: the running connector's inventory (Hermes skills, plugins, MCP servers, memory, rules) | Static analysis of directories and container images |
| Hosts | Jetson (needs a connected agent) | dgx-1, dgx-2, Jetson, Pi |
| Unit | user unit `homelab-aibom.timer` (03:15), `SyslogIdentifier=homelab-aibom` | system unit `cisco-aibom.timer` (01:30 on the Jetson), `SyslogIdentifier=cisco-aibom` |
| Reports | `~/.local/state/homelab-aibom/` | `/var/lib/cisco-aibom/` |

Both stay. The AI inventory dashboard shows both; they do not share names or files.

## Common tasks

```bash
# run now on one host (from dgx-1, hosts/)
~/.venvs/ansible/bin/ansible <host> -b -m systemd_service -a "name=cisco-aibom.service state=started"
# follow it / last summary
sudo journalctl -u cisco-aibom -f
# latest report
sudo ls -t /var/lib/cisco-aibom/ | head -1
# start the diff from scratch (e.g. after adding targets)
sudo rm /var/lib/cisco-aibom/<host>-*.json
```

Upgrade: bump `cisco-aibom` in `.github/requirements-aibom.in`, recompile with the command in its header, let the
`aibom` CI job pass, merge, then `ansible-playbook playbooks/aibom.yml` (the venv is rebuilt when the lock changes).
The first night after an upgrade may show added/removed components that are only scanner changes.
