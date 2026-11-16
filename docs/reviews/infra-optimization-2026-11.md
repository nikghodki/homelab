# Infrastructure optimization review, November 2026

| | |
|---|---|
| Date | 2026-11-16, measured 13:30–14:30 PST |
| Scope | All five hosts, k3s, the Docker stacks, the model plane (DGXMM, vLLM, LiteLLM), observability, CI, network, storage and backups, the security scanners, power and thermals |
| Builds on | [tool-review-2026-11.md](tool-review-2026-11.md) (tool choice, overlaps, licences) and [code-review-2026-11-15.md](code-review-2026-11-15.md) (defects). This review doesn't repeat their findings. It measures what they estimated and adds what only shows up in the numbers |
| Method | Read-only. Host tools (`free`, `ps`, `docker stats`, `k3s crictl stats`, `nvidia-smi`, `iw`, `ss`, `journalctl`), VictoriaMetrics and Loki queries on dgx-2, LiteLLM's Postgres (aggregates and key aliases only), DGXMM's SQLite (read-only), and the GitHub Actions API (336 runs, 2,317 jobs). Nothing was restarted, changed or deleted. The only active probe was one `iw scan` per Spark |
| Data window | VictoriaMetrics has data from 2026-11-15 02:06 PST (about 36 h). Loki keeps 30 days, but only the last 24 h were queried. The CI window is 37.8 h (2026-11-15 08:01 UTC to 2026-11-16 21:50 UTC) |
| Caveats | Three other agents (platform, ambient-agent build, observability) worked during the window. Their effects aren't counted as steady state: restarts, a k3s restart on the Jetson, a killed AIBOM run, alert episodes and part of the SSH traffic. These are marked where they matter. The window also includes the 2026-11-15 GPU OOM ([incident](../../docs-site/content/docs/operations/incident-gpu-oom.md)) |

**Bottom line.** The fleet has plenty of RAM except on the Jetson. The real costs are in three other places:

- **CI minutes.** 3,264 billable minutes in 37.8 h. The Free plan includes 2,000 a month.
- **Log volume.** 5.5 GiB a day of raw logs. 87 % of it comes from three sources: a RoboClaw poller on the Jetson, DGXMM's SSH polling of dgx-2, and agent SSH sessions. This noise also pushes the local journals out: dgx-2 keeps 21 h, and the Jetson about 4 h, in RAM.
- **The model plane's cold starts.** `qwen3.8-27b` started cold 13 times on 2026-11-16 and spent 57 minutes loading. About 93 % of its tokens went to two scanners, which hit their own rate limits 955 times.

Each of these is cheap to fix. Together the fixes would save about 75 % of CI minutes, about 4.8 GiB of logs a day and most cold starts.

---

## 1. Resources

### 1.1 Hosts (now, and over the 36 h of metrics)

| Host | RAM total | Used now | Available now | Used avg / max (36 h) | Swap used | Disk used | CPU avg 24 h |
|---|---|---|---|---|---|---|---|
| dgx-1 | 121.7 GiB | 79.3 GiB (model loaded) | 42.4 GiB | 50.8 / **111.9** GiB | 0.5 / 16 GiB | 1.2 / 3.7 TB (33 %) | 5 % |
| dgx-2 | 121.7 GiB | 9.2 GiB | 112.5 GiB | 16.4 / **114.2** GiB | 1.0 / 16 GiB | 652 GB / 3.7 TB (19 %) | 3 % |
| Jetson | 7.4 GiB | 3.5 GiB | 3.8–4.1 GiB | 3.5 / 5.3 GiB | **0.8 / 2 GiB** | 106 GB / 3.6 TB | **24 %** |
| Omarchy | 7.7 GiB | 2.5 GiB | 5.2 GiB | 2.2 / 2.6 GiB | 0 | 30 / 464 GB | 8 % |
| Pi | 3.7 GiB | 0.7 GiB | 3.0 GiB | 0.6 / 1.1 GiB | 0 | 29 / 940 GB | 8 % |

- Both Spark maxima are from 2026-11-15 22:45 UTC (14:45 PST), the GPU OOM. Outside that hour, dgx-1 peaked at 103 GiB and dgx-2 at 104 GiB (2026-11-16 00:20 UTC), both while models were loaded across the two Sparks.
- dgx-2's GPU did almost nothing. DCGM GPU utilisation averaged 0–3.7 % over 24 h, at 3.6–7 W. Every model ran on dgx-1.
- The Jetson's committed memory (`Committed_AS`, 8.1 GB) is more than its RAM. It is the only host that swaps under normal load.

### 1.2 Biggest processes per host (RSS or container working set)

| Host | Measured | Change since the tool review (2026-11-15) |
|---|---|---|
| dgx-1 | vLLM `qwen3.8-27b`: 61 GiB GPU (62,407 MiB in `nvidia-smi`) + 6.7 GiB process RSS. **LiteLLM 3.42 GiB** (4 workers at 706–734 MiB + master at 601 MiB). k3s-server 1.42 GiB. **GNOME + NVIDIA Sync 1.26 GiB** (four `nvidia-sync.bin` at 128–420 MiB, gnome-shell 155 MiB). Open WebUI pod 693 MiB working set. DGXMM 409 MiB. otelcol 235 MiB. LiteLLM Postgres 190 MiB | LiteLLM was 1.03 GiB on 2026-11-15, so it is now **3.3×**. It has no memory limit |
| dgx-2 | cisco-aibom 1.35 GiB (a run in progress). k3s-server 1.10 GiB. **Phoenix 553 MiB.** Loki 449 MiB. VictoriaMetrics 437 MiB. Argo CD application controller 409 MiB. Grafana 276–350 MiB. The two OTel gateways 120 + 124 MiB. Temporal (4 containers) about 210 MiB | Phoenix was 48 MiB, so 11×. Loki was 315 MiB and VictoriaMetrics 243 MiB; both grew with the data |
| Jetson | DefenseClaw gateways 809 MiB (577 + 127 + 53 + 52). Hermes 586 MiB (303 + 283). Home Assistant 527 MiB. k3s-server 258 MiB. **journald in RAM about 148 MiB** (§3.4). otelcol 127 MiB (peak 206 MiB). Zenoh 44 MiB. LiveKit 27 MiB | LiveKit was 337 MiB; without `--dev` it is now 27 MiB |
| Omarchy | quickshell 320 MiB (desktop). otelcol 215 MiB. k3s-agent 190 MiB. **two `journalctl` at 105 + 69 MiB** (otelcol's reader and a stray `-f`). Homepage 129 MiB. ntfy 31 MiB. Gatus 29 MiB | — |
| Pi | **otelcol 223 MiB**, against its own `MemoryMax=256M` (87 %). Desktop (labwc, panel, pcmanfm) about 0.21 GiB. picoclaw about 90 MiB. ROS/LiDAR nodes under 80 MiB each | Unchanged |

### 1.3 k3s requests and limits against actual use

There is no metrics-server and no cAdvisor scrape. The working sets below come from `k3s crictl stats`.

| Pod (node) | Request / limit | Working set | Verdict |
|---|---|---|---|
| open-webui (dgx-1) | 1 Gi / 3 Gi | 693 MiB | Request about 1.5× use. Fine |
| argocd-application-controller (dgx-2) | 384 Mi / 768 Mi | 409 MiB | Right-sized (`GOMEMLIMIT=600MiB`, decision 0006) |
| ops-db-1, ops-db-2 (CNPG) | 256 Mi / 768 Mi | 67 / 52 MiB | Over-requested 4–5× (new; the ambient-agent session) |
| kyverno-admission ×2 | 128 Mi / 384 Mi | 74 / 62 MiB | Fine |
| everything else (edge, kube-vip, CoreDNS, kube-state-metrics, MCP servers) | 16–70 Mi | 5–53 MiB | Fine |

- All pods together use about 1.3 GiB on dgx-1 and 0.65 GiB on dgx-2. Requests don't matter on 121 GiB nodes.
- **No pod runs on the Jetson or Omarchy.** The Jetson's 2.3 GiB allocatable is bookkeeping only, not a RAM cost.
- **The Docker stacks are the unbounded part.** Only `ml` (MLflow 1 g, its Postgres 512 m, ml-api 128 m) and `sim` (16 g) set `mem_limit`. LiteLLM, Phoenix, Loki, VictoriaMetrics, Grafana, Temporal and DGXMM have no cap. On GB10, every MiB a service grows after a model loads comes out of the model's safety margin.

### 1.4 GPU-OOM headroom on the Sparks

| Guard | Setting (measured) | Note |
|---|---|---|
| DGXMM planner | `safety_margin_gib` 8 + `os_reserve_gib` 4 (defaults, `dgxmm/config.py`) | Plans against free memory at load time. Services that grow later aren't re-checked |
| `gpu-oom-guard` | kills the largest GPU process below 6,144 MiB available, 1 s interval | Fired once (2026-11-15 15:19, killed a 104 GiB process). **Not in Git** (the incident's open follow-up) |
| earlyoom | `-m 4,2 -s 100,100`, so SIGTERM at 4 % (4.9 GiB) and SIGKILL at 2 %. The avoid list holds sshd, systemd, journald, dockerd, containerd, tailscaled and the guard | **`k3s-server` (etcd) isn't avoided**, and there's no `--prefer` for the engines. Not in Git |
| vmalert `FleetMemoryLow` | free + cached < 2 GB for 10 min | **Fires only after both guards have acted** (they act at 6 and 4.9 GiB). On a Spark it can't warn in time |
| vLLM `qwen3.8-27b` | `--gpu-memory-utilization 0.4807` (58.5 GiB), `--max-model-len 256000`, `--max-num-seqs 8`, fp8 KV, prefix caching, DFlash speculative decoding | KV capacity 1,672 blocks × 1,648 tokens = 2.76 M tokens. Use in this engine's life: **16 % KV, at most 2 running, 0 waiting, 0 preemptions** (§5.4) |

- **Headroom now.** dgx-1 with `qwen3.8-27b` loaded has 42 GiB available. The next on-demand models need 45–48 GiB each (`qwen3-coder-30b` 45.7, `nanbeige` 45.2, `twil-8b` 47.9). So none of them fits next to it today, and DGXMM must queue them. It does ("queue when memory is busy").
- **The OOM path that is left.** A model is loaded, then a service grows: LiteLLM (+2.4 GiB in a day), an AIBOM run (5.0–5.3 GiB peak on dgx-1, cap 6G) or Open WebUI (limit 3 GiB). That shrinks the 12 GiB margin with no re-plan. No alert fires before the guard kills the engine.

### 1.5 The Jetson's 8 GB and the Pi's 4 GB

- **Jetson.**
  - Of the host-installed services, the DefenseClaw gateways (0.81 GiB) and Hermes (0.59 GiB) are the largest. One gateway per host is tool review #12, a decision.
  - Two things the tool review didn't see:
    - The journal lives in RAM (`/run/log/journal`, 148 MiB; there is no `/var/log/journal`).
    - The RoboClaw control-center poller costs CPU and log volume (§3.2). The Jetson's 24 % CPU average is the highest in the fleet; in a 3 s sample the top consumers were k3s-server (restarting, platform work), the DefenseClaw gateway and Home Assistant.
  - Cisco AIBOM's code scans (1.1–1.24 GiB, tool review §6) are moving to dgx-2 in #121.
- **Pi.** Comfortable (3.0 GiB available). The one risk is otelcol at 87 % of its own 256M cap: the cgroup would OOM-kill the collector before the host is short of memory. The desktop is D17 (Lite reinstall).

---

## 2. Duplication, overlap and idle things

The tool review's verdicts stand: NATS and Mosquitto are kept (§2.3), and so are Tempo and Phoenix (§2.4) and Gatus (§2.5). These are new or measured here:

| What | Measured | Recommendation |
|---|---|---|
| **Phoenix** grew from 48 to 553 MiB RSS; its volume is 629 MB after about 34 h (≈ 0.44 GB/day) | Sending full judge and AIBOM prompts (20 k tokens average, §5.3), with no retention set in the compose file | Set a retention policy (architecture §11 says 30 days, about 13 GB at this rate). Consider not tracing the scanner keys (`defenseclaw-jetson-judge`, `cisco-aibom`): they make 93 % of the tokens and aren't the agent traffic Phoenix is for |
| **Gatus and vmalert check the same things** | k3s API and etcd (Gatus `k3s_*` + `K3sApiDown`/`K3sEtcdMemberDown`), front door (Gatus `web_*`/`edge_*` + `EdgeFrontDoorDown`/`EdgeReplicasDown`), Grafana (Gatus + `ObservabilityComponentDown`) | Keep both paths (decision 0009: the Dell path must survive the Sparks). But send only one push per symptom: give the vmalert copies of the outside-in checks a non-paging severity, or drop them where Gatus already covers the symptom |
| **Two OTel gateways on dgx-2** | 120 + 124 MiB | As tool review §2.16: keep unless memory gets tight |
| **Six Caddy instances** (2 edge pods, fleet-caddy, ml-api, status-gate, ops-docs) | 12–20 MiB each | As tool review §2.2 and decision 0011 |
| **Idle listeners** | Jetson `iperf3` on `*:5201` and a systemd socket on `*:6566` (SANE). Pi `rpcbind` on `0.0.0.0:111`. dgx-1's iperf3 and NFS were stopped on 2026-11-15 (tool review §6), but these two hosts were missed | Stop and disable them (attack surface, no RAM saving) |
| **Temporal**: 8,832 metric series while it runs few or no workflows | 16 % of all active series (§3.5) | Keep the service (the ambient agent is about to use it, with mTLS in progress). Drop its latency histograms at the scrape, or scrape at 120 s |
| **Stopped containers and images** | See §7.3 | Clean up after the rollback dates |
| **`mcpg-probe`** (grafana/mcp-grafana 2.3.0) on dgx-1 | Up 48 min | A test container from the ambient-agent session. Leave it to them |

---

## 3. Observability cost

### 3.1 Loki ingest (24 h, raw bytes as Loki counts them)

| Host | Bytes/day | Lines/day | Share of bytes |
|---|---|---|---|
| Jetson | **2.39 GiB** (2.28 journald + 0.11 DefenseClaw) | 1.88 M | 44 % |
| dgx-2 | **2.00 GiB** (+ 33 MiB edge-caddy) | 1.88 M | 37 % |
| dgx-1 | 0.77 GiB (+ 31 MiB edge-caddy, 2 MiB DefenseClaw) | 0.72 M | 14 % |
| Omarchy | 0.13 GiB | 0.12 M | 2 % |
| Pi | 0.07 GiB | 0.06 M | 1 % |
| **Total** | **5.4 GiB/day** | **4.67 M** | |

- The Loki volume is 507 MB after about 36 h, so compression is about 15×. Disk is not the problem: 30 days ≈ 10 GB.
- The costs are elsewhere: CPU and Wi-Fi on every collector, and the **local journals** (§3.4).

### 3.2 The noisy sources

| # | Source | Volume | Cause | Fix |
|---|---|---|---|---|
| N1 | Jetson `control-center.service` (user unit, RoboClaw Control Center, uvicorn on `:8200`) | **1.66 M lines, 2.1 GiB/day**: 88 % of the Jetson's logs, 38 % of the fleet's. About 14.7 k error-like lines an hour | Its poller (`app/poller.py` → `clients.py` `get_status`, `get_detections`, `get_battery`) can't reach its endpoint (`httpx.ConnectError: All connection attempts failed`). It logs a full traceback, about 20 lines, for each call: about 105 tracebacks every 2 minutes | Back off and log one line per state change. If it isn't in use, stop the unit **[decision]**. It is a read-only poller, and stopping it doesn't move the robot |
| N2 | dgx-2 `sshd` | **≈ 1.56 M lines, ≈ 1.8 GiB/day**, a flat 65 k lines/h for 15 h | **DGXMM reaches dgx-2's Docker over SSH** (`ssh://nikghodki-dgx-2@10.100.136.2`, key comment `dgxmm-node-key`). It opens a new session for each call, about 49 a minute, with `scrape_interval_s` 5 and `budget_interval_s` 2. `LogLevel VERBOSE` (role `hardening`) turns each session into about 11 lines | DGXMM: `ControlMaster auto` + `ControlPersist 10m` in its `DGXMM_SSH_CONFIG`, or poll `dgxmm-node-probe` over HTTP (DGXMM session). The collector could also drop sshd's `Accepted key … found at`, `Postponed publickey` and `Connection from` lines |
| N3 | dgx-1 `sshd` | ≈ 0.72 M lines, ≈ 0.9 GiB/day (30 k lines/h) | Agent sessions through the laptop tunnel (`127.0.0.1`, about 16 a minute while agents work), with the same VERBOSE level | Same collector filter. Agents could use one multiplexed connection (`ControlMaster`) |
| N4 | Jetson `k3s` | 100 k lines/day | kube-router's NetworkPolicy sync fails about 101 times an hour (`iptables-restore … Extension NFLOG revision 0 not supported`) and dumps the whole ruleset each time | **Overlap: platform** (worktree `fix/jetson-netpol-nflog`). The log volume is a symptom. The real issue: **NetworkPolicies may not be enforced on the Jetson** until it is fixed |
| N5 | Omarchy `otelcol-contrib` | 38 k lines/day | The hostmetrics `filesystem` scraper gets `permission denied` on `/run/media/nikghodki/OMARCHY_202609` (the installer USB stick, iso9660, still mounted) every 30 s, with a stack trace | Unplug the stick, or exclude `iso9660` and `/run/media/*` in `config.yaml.j2` |
| N6 | Jetson `tailscaled` | 31 k lines/day | `dns: resolver: forward: no upstream resolvers set, returning SERVFAIL`, about 720 an hour (some rate-limited) | A real DNS fault: something on the Jetson queries `100.100.100.100` for non-tailnet names, and Tailscale has no upstream. Check `tailscale set --accept-dns` against systemd-resolved's per-link DNS (`192.168.86.1`) |
| N7 | Pi `wpa_supplicant` | 26 k lines/day | `CTRL-EVENT-REGDOM-CHANGE init=CORE type=WORLD`, about 1,080 an hour: **no Wi-Fi country is set** | Set the country (`raspi-config nonint do_wifi_country US` or `iw reg set US` persistently). With `WORLD`, many 5 GHz channels are passive-only. Do it with the robot docked **[timing]** |

**Every journald record is shipped whole.** The collector's `journald` receiver sends the entire JSON export as the body: `_CMDLINE`, `__CURSOR`, `_BOOT_ID`, `_CAP_EFFECTIVE`, `_SELINUX_CONTEXT` and 25 more fields, about 1.2 KB a line. A `transform` processor that keeps `MESSAGE` and moves `PRIORITY`, `SYSLOG_IDENTIFIER`, `_SYSTEMD_UNIT`, `_SYSTEMD_USER_UNIT` and `_PID` into attributes would cut the remaining bytes by an estimated 60–70 % (e). It would also stop shipping **process command lines**, which can hold secrets, to Loki. Code review #37 (OTLP without TLS) makes that worse today, since the lines travel in cleartext over Wi-Fi.

### 3.3 Savings

- Fixing N1, N2 and N3 removes about **4.8 of 5.4 GiB/day (≈ 87 %)**, leaving about 0.7 GiB/day.
- Slimming the records takes that to about 0.25–0.3 GiB/day (e).
- N4 to N7 are about 0.2 GiB/day together. They matter more as faults than as volume.

### 3.4 Local journal retention (what the noise costs at incident time)

| Host | Journal | Oldest entry | Note |
|---|---|---|---|
| dgx-1 | 1.0 G (cap 1G) | 2026-10-15 | Fine |
| dgx-2 | 1.0 G (cap 1G) | **2026-11-15 16:36 (≈ 21 h)** | The previous boots, including the OOM journals the incident write-up used, have already rotated out. N2 is the cause |
| Jetson | **volatile**, 148 MB in `/run` (RAM) | **2026-11-16 09:57 (≈ 4 h)** | No `/var/log/journal`. Lost at every reboot. N1 fills it |
| Omarchy | 135 MB (cap 1G) | — | Fine |
| Pi | 68 MB (cap 300M) | — | Fine |

The ambient agent's design reads previous-boot kernel journals through `ops-ro` (G1 in [ambient-agent-design.md](../ambient-agent-design.md)). On dgx-2 and the Jetson those journals are gone. Fix N1 and N2, and give the Jetson persistent journald storage on its NVMe (`Storage=persistent`, keep `SystemMaxUse=500M`). That frees about 150 MiB of RAM on the tightest host.

### 3.5 Metrics (VictoriaMetrics)

- 56,042 active series, 1,163 samples/s, `vm_data_size` 56 MB after 36 h. A linear estimate for 12 months is about 14 GB (e). That is cheap.
- Biggest jobs: `temporal` 8,832 (16 %), Grafana's own metrics 6,001 (11 %), Loki 3,515, Argo CD server 2,380, kube-state-metrics 2,054, VictoriaMetrics 1,930, DefenseClaw 1,681.
- `system_network_*`: 104 devices, of which **87 are `veth*`/`cni*`/`flannel*`/`docker*`/`br-*`**. They churn with every pod and container. Exclude them in `hostmetrics.network`.
- dcgm-exporter's `Hostname` label is the container ID. Each restart (two per Spark in the 36 h) makes a new set of series and breaks continuity in dashboards. Drop the label at the scrape.
- Not scraped at all: **vLLM's `/metrics`** (KV use, queue, TTFT, prefix-cache hits, spec-decode acceptance). The model-plane facts in §5.4 had to be read by hand. Scraping it (through DGXMM or the engine port) is the cheapest way to tune P2.7.

### 3.6 Alert quality (36 h)

Alert episodes were counted from `ALERTS` at a 1 min step. An episode is a rising edge.

| Alert | Episodes | Finding | Fix |
|---|---|---|---|
| **FleetHostHot** dgx-1 | **45 pending, 0 firing** | Threshold 85 °C on `max(fleet_temperature_celsius)`. GB10's `acpitz`: median 58.8 °C, max 94.1 °C, 76 minutes above 85 (longest run 11 min). The ACPI critical trip is **104.8 °C**. `nvidia-smi` counters since boot (22.6 h): SW thermal slowdown 87 s, HW thermal slowdown 5.5 s | Per hardware: GB10 > 95 °C for 15 min, plus an alert on growth in the throttle counters (DCGM clock-event reasons); keep 85 °C for x86 and Orin. That removes about 45 useless pending states per 36 h |
| ObservabilityComponentDown | 30 pending, 8 firing | `up == 0` for 5 min on every job. Most episodes are restarts by the other agents (Argo CD, Kyverno, Gatus, kube-state-metrics); the 15–17 min firing on dgx-1, the Jetson and the Pi was the k3s or collector work | `for: 10m`. Split host collectors (page) from in-cluster exporters (warn, Argo CD already alerts on unhealthy apps) |
| ArgoCDAppNotHealthy / OutOfSync | 10 / 8 pending | Deploys in progress | Fine as is (pending only) |
| FleetMemoryLow | 0 | Can't fire usefully on the Sparks (§1.4) | MemAvailable < 12 GiB for 5 min on GB10 hosts (the DGXMM margin), before the 6 GiB guard |
| Gatus `web_ha-nghodki-ai` | 562 failed checks (about 9.4 h at 60/h), since fixed | A long outage, not flapping. Gatus alerts once per outage | — |
| Alertmanager | 239 webhook notifications, all the `Watchdog` heartbeat to Gatus; 0 failed | Routing is clean | — |

---

## 4. CI (GitHub Actions, private repo, Free plan)

### 4.1 Minutes

The window is 37.8 h. Billable minutes are the sum over jobs of each job's duration rounded up to a whole minute, which is how GitHub bills.

| Workflow / event | Billable min | Raw min | Runs |
|---|---|---|---|
| pr-checks / pull_request | 1,854 (57 %) | 1,106 | 174 |
| **pr-checks / push to main** | **1,343 (41 %)** | 801 | 136 |
| build-sign | 33 | 28 | 8 |
| Dependabot dependency graph | 21 | 14 | 14 |
| nightly-scan | 13 | 11 | 4 |
| **Total** | **3,264** | **1,959** | 336 |

- **2026-11-16 alone used 2,363 billable minutes** (to 21:50 UTC), more than the Free plan's **2,000 minutes a month**. 56 jobs (7 runs) failed with zero duration at about 04:00 UTC: the spending-limit block.
- **Rounding costs 40 %** (1,305 of 3,264 min). `pr-checks` runs 8 parallel jobs, and five of them take about a minute or less but bill one or two: Secret scanning 15 s, Kubernetes 12 s, Docs 21 s, AI scanners 60 s, Unit tests 61 s.
- **The push-to-main run repeats the PR run** for a squash merge of the same tree, which is 41 % of all minutes.

### 4.2 Per job and per PR

| Job (median / p90) | Median duration | Where the time goes (median step) |
|---|---|---|
| AI BOM (Cisco AIBOM) | 110 s / 147 s | Repo scan 110 s; install 28 s |
| Lint | 82 s / 115 s | ansible-lint 48 s; tool install 30 s |
| Unit tests | 61 s | Install 32 s; the `measure.sh` stub test 16 s |
| AI scanners | 60 s | Install 30 s |
| Code scanning | 55 s | Semgrep 20 s; Trivy 14 s |
| Docs site | 21 s | Install 12 s |
| Secret scanning | 15 s | gitleaks 4 s; TruffleHog 4 s |
| Kubernetes | 12 s | kubeconform + Kyverno 9 s |

- Installing tools takes about **132 s per run** across jobs, with no pip cache: every job reinstalls from hash-locked requirements.
- **140 PRs** in the window. Per PR: median 11 billable min on the PR event, p90 24, max 64; 1.24 runs per PR on average. Each merge adds about 9.9 min for the push run, so the total is **about 23 min per merged PR**. At that rate the Free quota covers **about 87 PRs a month**. This week's pace was about 90 PRs a day.
- **20 of the 140 PRs touched only docs** (`docs/`, `docs-site/`, `runbooks/`, `decisions/`, `*.md`). They used 275 billable min and ran all 8 jobs. No job has `paths`/`paths-ignore`.
- Concurrency: `cancel-in-progress` works for PRs (91 cancelled jobs), but cancelled jobs still bill their started minutes.

### 4.3 What to change (in order of minutes saved)

| # | Change | Saves (e) | Risk |
|---|---|---|---|
| C1 | **Drop the `push: [main]` trigger** from `pr-checks`. Keep `workflow_dispatch`, and let the nightly job run the full suite once on `main` (merge skew is caught within a day) | −41 % (≈ 9.9 min per merge) | A broken main is found up to a day later. The PR run has already passed on that tree, rebased (squash-only) |
| C2 | **Consolidate 8 jobs into 2**: a "fast" job (lint, secrets, Kubernetes, docs, unit tests; ≈ 150 s after one checkout) and a "scan" job (code scanning, AI scanners, AIBOM) | ≈ −4 min per run (rounding and repeated setup) | Less parallelism, so a run takes about 1–2 min longer to finish |
| C3 | **Path filters.** Docs-only PRs run only docs + secrets + yamllint. AIBOM and the AI scanners run only when `tools/`, `hosts/`, `robots/`, `cluster/`, `.github/` or Python/agent code change (`dorny/paths-filter` pinned by SHA, or `paths` on a split workflow) | ≈ −2 to −3 min on most PRs; docs-only PRs from 8 jobs to 1 | A scanner might miss a file type outside the filter. Keep the nightly full run |
| C4 | `actions/setup-python` with `cache: pip` keyed on the hash-locked requirement files (code review #56 left this undone) | ≈ −60 to −90 s per run of install time | None (hashes are still checked) |
| C5 | Self-hosted runner on dgx-2 (plan P4.8, decision 0001) for the scan job | Most of the remainder | A home runner on a private repo: isolate it (ephemeral, no host mounts, egress-limited). Check GitHub's current pricing for self-hosted minutes before relying on it |

- **C1 to C4 together: about 5–6.5 billable min per merged PR instead of about 23 (−72 to −78 %).** At this week's volume that is about 900 instead of 3,264 min.
- On Free (2,000 min) that covers about 300 PRs a month instead of about 87. At a sustained 10 PRs a day it is about 2,300 min a month: still over, so C5 remains the structural fix.

---

## 5. Model plane

### 5.1 Routes and use

From LiteLLM `SpendLogs` (30 days; in practice 2026-11-16, see §7.4) and `DailyModelUsage`. Counts only.

| Route | Requests | Success | Prompt / completion tokens | Avg / p95 latency | Note |
|---|---|---|---|---|---|
| `qwen3.8-27b-nothink` | 1,457 | 86 % | 5.39 M / 258 k | 12.3 s / 29.6 s | Only `defenseclaw-jetson-judge` (key alias) |
| `qwen3.8-27b` | 853 | **59 %** | 14.86 M / 71 k | 5.8 s / 19.0 s | Failures: 429 (cisco-aibom 340, judge 289), 500 (53) |
| `twil-8b` | 1 | 0 | — | — | 403 (two keys not allowed) |
| `qwen3-coder-30b-a3b-instruct-fp4`, `nanbeige4.3-33b-nvfp4`, `flint-nvfp4` | **0** | — | — | — | Registered by DGXMM; no LiteLLM traffic in 30 days. flint was started 6 times in DGXMM directly |
| no model (`/v1/models`, bad keys) | 53 | — | — | — | `DailyRequestErrors` counts 183 × 401 on 2026-11-16 (bad or old keys), 46 of the logged ones at 19:00 UTC |

### 5.2 Token use by consumer (key alias)

| Key alias | Requests | Prompt tokens | Completion tokens | Share of tokens |
|---|---|---|---|---|
| `cisco-aibom` | 809 | 13.53 M | 42 k | **66 %** |
| `defenseclaw-jetson-judge` | 1,456 | 5.39 M | 258 k | **27 %** |
| `hermes` | 13 | 0.96 M | 4.5 k | 4.7 % |
| `claude-code` | 12 | 185 k | 1 k | 0.9 % |
| `open-webui` | 11 | 117 k | 15 k | 0.6 % |
| `ops-agent` | 7 | 63 k | 9 k | 0.3 % |
| `picoclaw-pi` | 2 | 116 | 57 | ~0 |

- Scanners make **93 % of the tokens and 98 % of the requests**. Peak load was 19 requests a minute and 6 in one second; the average was 3.6 a minute.
- **955 requests were refused with 429** (`ProxyRateLimitError`) on 2026-11-16, all from the keys' own limits:
  - `cisco-aibom` (10 rpm, 1 in flight): 340.
  - `defenseclaw-jetson-judge` (60 rpm, 6 in flight): 615.
- The AIBOM timers on dgx-1 (04:20) and dgx-2 (04:22) start two minutes apart and **share one key that allows one request in flight**. So the 429s are guaranteed (§8).

### 5.3 Cold starts and keeping `qwen3.8-27b` warm

From DGXMM's `deployment_events` (read-only).

- **61 cold starts since 2026-10-16. 13 on 2026-11-16, with 57 minutes spent loading.** Start to ready: median **274 s**, p90 316 s, max 831 s.
- The idle timeout is DGXMM's default, **300 s** (`ondemand_idle_timeout_s`; `idle_timeout_s` is unset for the deployment).
- The model rarely stays asleep for long. Of 18 sleeps since 2026-11-15, **13 ended within 60 minutes** (11–21 min typical) and only 5 lasted longer (151–455 min). The pattern 17:04, 17:48, 18:30, 19:12, 19:56 is the Jetson judge waking it every ≈ 43 min.
- On 2026-11-16 the model was loaded for **13.2 h of the 20.5 h** (65 %) plus 57 min loading.
- Every cold start is longer than DefenseClaw's fixed 120 s plugin-watcher timeout (decision 0012). So the first judge call after each sleep times out, and the plugin is quarantined, fail closed.
- **Is keeping it warm worth the memory?** It costs 58.5 GiB reserved on dgx-1, which is otherwise idle (5 % CPU; nothing else on-demand got traffic). The other on-demand models can't run next to it anyway (§1.4).
  - Idle timeout 3,600 s: avoids **13 of 18** recent restarts (72 %), saving about 40 min of loading and 13 judge timeouts a day. The extra memory-time is the 5–25 min tails that are slept through today.
  - Always on: frees nothing, but removes cold starts entirely.
  - **[decision]**, and an overlap with the DGXMM session (P2.0, P2.7).

### 5.4 KV cache and batching (this engine's life, about 1 h)

- Load: 166 requests, 3.30 M prompt tokens, 51.8 k generated. The traffic is prefill-heavy (about 20 k prompt tokens and 310 output tokens per request).
- Prefix cache hit rate **67 %**. TTFT 5.6 s average; end-to-end 16.9 s average; queue time 37 ms average.
- Speculative decoding (DFlash) accepted **42 %** of draft tokens (38.5 k of 91.2 k).
- **KV use 16 % with 2 running.** The KV pool (2.76 M tokens) is about 6× what 8 concurrent 20 k-token prompts need, and more than the 8 × 256 k worst case.
  - `--gpu-memory-utilization` ≈ 0.38–0.40 would still hold well over 1 M tokens.
  - It would return an estimated **10–14 GiB** to dgx-1's margin (e; DGXMM's calibration must confirm: measured footprint 55.2–56.6 GiB against an estimate of 48.7 GiB).
  - **Overlap: DGXMM session.**
- `--max-num-seqs 8` is fine: there was no queueing, and the judge's 6-in-flight limit is below it.

### 5.5 LiteLLM itself

- 4 workers use 3.42 GiB on dgx-1 for 0.06 requests per second on average (0.3 at peak).
- The k3s move in progress (`litellm-k3s`, P3.7) uses **2 pods × 2 workers** (limit 3 Gi each), which is about the same memory. **1 worker per pod** (two pods still give HA) would use about 2.6 GiB, saving about 1.4 GiB (e). **Overlap: platform.**
- The proxy logs about 0.9 MB/h at `INFO` (22 MB in 12 h).

---

## 6. Network

### 6.1 Wi-Fi (both Sparks are still on Wi-Fi; P0.11 Ethernet is planned)

| Host | Associated | Link | Better option seen in the scan (`iw scan`, dBm) |
|---|---|---|---|
| **dgx-2** | `nikghodki_wifi`, 6 GHz ch 133 (6615 MHz, 160 MHz) | **−72 dBm** (scan −74), tx HE-MCS 3 NSS 1, rx HE-MCS 1, 288 Mbit/s | **Same AP (BSSID `90:ca:fa…`) on 5 GHz ch 149 (5745 MHz) at −64 dBm**, 8–10 dB stronger. The same AP on 2.4 GHz (2437) at −54 dBm. A second network `nikghodki_wifi_1` (`d4:6c:6d…`, apparently the ISP gateway) on 5220 MHz at −64 dBm |
| dgx-1 | 5 GHz ch 149 (5745 MHz, 80 MHz) | **−75 dBm**, tx HE-MCS 2, 216 Mbit/s | The same AP on 2.4 GHz at −54/−58 dBm. 5 GHz `nikghodki_wifi_1` at −71. Nothing much better on 5/6 GHz |
| Jetson | 2.4 GHz ch 11 | −59 dBm, tx MCS 2 (19.5 Mbit/s), rx 130 | — |
| Omarchy | 5 GHz ch 149 | −63 dBm, 260/390 Mbit/s | — |
| Pi | 5 GHz ch 149 | 54 % | Regulatory domain `WORLD` (N7) |

- Latency from dgx-1, 60 pings at 0.25 s:

  | Target | Average | Max | mdev |
  |---|---|---|---|
  | dgx-2 over Wi-Fi | 22.2 ms | **149 ms** | 26 ms |
  | dgx-2 over the cable | 0.31 ms | 0.75 ms | — |
  | Jetson | 16.6 ms | 119 ms | — |
  | Omarchy | 15.1 ms | 58 ms | — |
  | Pi | 17.1 ms | 108 ms | — |
  | router | 8.4 ms | 74 ms | — |

- **Recommendation for dgx-2 until P0.11:** lock its connection to 5 GHz (`nmcli connection modify <conn> 802-11-wireless.band a`; optionally pin the BSSID of the ch-149 radio). That is about +8–10 dB, which at 80 MHz should mean MCS 7–9 instead of MCS 1–3 (e). **[decision]**: it is a network config change on a k3s server, so do it with the Jetson healthy (decision 0005, R1). The real fix stays P0.11.

### 6.2 The QSFP cable is underused

- Since boot, dgx-1 moved **5 GiB in / 3 GiB out on the cable** and **15 GiB in / 6 GiB out on Wi-Fi**. The second cable (RDMA, `enP2p1s0f0np0`) moved 0.
- **Spark-to-Spark traffic on Wi-Fi that could use the cable:**
  - dgx-1's OTel collector and DefenseClaw OTLP go to dgx-2 over the LAN: `observe_host: 192.168.86.36` in `group_vars/all.yml`, connections `192.168.86.44 → 192.168.86.36:4317/4319`. Fix: a `host_vars/dgx-1.yml` override to `10.100.136.2`, since the observe ports listen on all interfaces. A quick win.
  - When the VIP is on dgx-1, the front door's upstreams for Grafana (`:3000`), Phoenix (`:6006`), Pocket ID (`:1411`) and the Temporal UI (`:8233`) go to `192.168.86.36`, a second Wi-Fi hop. Grafana and Phoenix listen on `0.0.0.0` and could use `10.100.136.2` now. Pocket ID and the Temporal UI are bound to the LAN address only. **Overlap: platform (front door)**; also code review #33 (exposure).
- **Tailscale paths are all direct:**
  - Jetson and Pi through the LAN (`192.168.86.x:41641`).
  - dgx-2 through flannel over the cable (CurAddr `10.42.0.1`, routed through `flannel.1` on `enp1s0f0np0`).
  - No peer is on DERP (home DERP SFO). #141 has just stopped peers from using the kube-vip VIPs as endpoints.

---

## 7. Storage and backups

### 7.1 restic

| Repo (on dgx-2 `/srv/homelab-backup`) | Size | Snapshots | Last run |
|---|---|---|---|
| jetson | 323 MB | 2 | nightly |
| dgx-1 | 21 MB | 2 | 2026-11-16 02:40, +8.7 MB stored |
| pi | 6.0 MB | 2 | 2026-11-16 02:49, +40 KiB |
| dgx-2 | 1.3 MB | 2 | 2026-11-16 02:42, +45 KiB |
| omarchy | — | — | timer removed. Its last run (2026-11-15 03:38) failed to reach `backup.nghodki.ai:8000` |

- Retention runs server-side, weekly: `--keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune`, with append-only clients. That is sound. Growth is about 9 MB a day, which is negligible.
- **Backups are running, against decision 0002.** P1.10 still waits for your choice.
- **What isn't backed up, and matters:**
  - **Pocket ID's data volume** (`console_pocket-id-data`, 5.3 MB: every passkey and OIDC client).
  - MLflow's Postgres (70 MB) and artifacts, Temporal's Postgres (77 MB), Grafana (295 MB), Alertmanager (silences), Phoenix (629 MB).
  - All of these are named Docker volumes, and dgx-2 backs up only `/opt/homelab`.
  - In k3s: etcd snapshots stay local (2 × 30 MB on dgx-1, k3s default), and the new CNPG `ops-db` has no backup (P3.8).
- dgx-2's own backup sits on dgx-2, and every repo is on dgx-2. A dgx-2 disk loss takes all of them. The off-site target is on hold (design open question 4).
- dgx-1 still backs up the retired front-door paths (`edge-gateway/conf`, `edge-gateway/dnsmasq`, `voice-assistant/nginx`). Drop them after the 2026-11-22 rollback date.
- If backups go on: add `pg_dump` pre-commands for MLflow and Temporal (like LiteLLM's), the Pocket ID volume, `etcd-snapshot` files and Grafana. Then add the off-site copy. **[decision]**

### 7.2 Docker log rotation (code review #28)

| Host | `daemon.json` log options | json-file logs now | Grower |
|---|---|---|---|
| dgx-1 | none | 46 MB | `litellm-proxy` 22 MB in 12 h (≈ 44 MB/day, ≈ 16 GB/year unbounded) |
| dgx-2 | none | 5.5 MB | — |
| Jetson | none | 1.4 MB | — |
| Omarchy | yes | 2.6 MB | — |
| Pi | no Docker | — | — |

Low impact today. The cheapest fix that doesn't restart `dockerd` (and so doesn't restart every container): an `x-logging` anchor (`max-size: 20m`, `max-file: 3`) in each compose stack, which takes effect at each stack's next deploy. `daemon.json` in `base` is the complete fix, applied at the next planned Docker restart. **[decision, code review #28]**

### 7.3 Images, layers and stopped containers (reclaimable, nothing deleted)

| Host | Images reclaimable | Build cache | Notable unused images | Stopped containers |
|---|---|---|---|---|
| dgx-1 | **36.6 GB** (21 dangling) | 1.7 GB | `dgx-vllm-whisper:2026-09-05-audio` **23.4 GB** (its route was removed 2026-11-15). `playwright/python` 2.5 GB. `litellm:rollback-1.100.0` + `main-latest` 2.4 GB. `dgxmm-llamacpp-rpc` ×2 5.3 GB. `renovate:latest` 1.3 GB. dcgm-exporter 4.4.2 0.8 GB | `open-webui` (rollback until 2026-11-23). `edge-caddy`, `nginx-gateway`, `edge-dnsmasq` (until 2026-11-22). `dmm-qwen38-inference` (3 weeks, 287 MB). `sdd-check-nccl`. `race-*` ×4 (microduck, another project) |
| dgx-2 | 12.2 GB | **33.4 GB** | `isaac-lab:3.0.0-kitless` base 16.3 GB (shares layers with the homelab build). The superseded `mujoco-playground:0.2.0-jax0.9.2` 12.4 GB. `dgxmm-llamacpp-rpc` ×2 10.7 GB. `home-assistant:<none>` 3.5 GB | `sdd-check-nccl` |
| Omarchy | 0.3 GB | 0 | — | — |
| Jetson | 0 | 1.4 GB | — | — |

- After the rollback dates, `docker image prune` / `builder prune` (with a filter for images newer than 7 days) frees about **84 GB** across the Sparks. Disk is at 33 % and 19 %, so this is housekeeping, not urgency.
- Model caches on dgx-1: `~/.cache/huggingface` 472 GB + `~/models` 305 GB.
  - Duplicates: `Qwen3.8-27B-NVFP4` 22 GB and `Qwen3-8B` 16 GB in both places.
  - Unserved: `Qwen3.8-27B` BF16 58 GB, its GGUF 43 GB.
  - Cluster-only: `DeepSeek-V4-Flash` 156 GB and `GLM-4.7-GGUF` 191 GB, started 3 and 1 times.
  - About 486 GB in all. **[decision]**: deleting means re-downloading them later.

### 7.4 LiteLLM's database

- `LiteLLM_SpendLogs` is 103 MB, of which 79 MB is TOAST. It holds **23,157 rows from September 2026 (74 MB)**, although `maximum_spend_logs_retention_period: 30d` is set, so the cleanup job doesn't remove them.
- There are no 2026-11-15 rows, although `DailyModelUsage` counts 345 requests that day.
- Check whether retention is enterprise-gated in 1.109.1 before relying on it. The Postgres move into CNPG (in progress) is the moment to drop the old rows.

---

## 8. Security tooling overhead

| Tool | Where | Run time | Peak memory | Finding |
|---|---|---|---|---|
| Cisco AIBOM | dgx-1 | 15–16 min normally. **2 h 25 min and failed on 2026-11-16** | 5.0–5.3 GiB (cap 6G) | The LLM stage's 429s (§5.2) stretched it. Its cap uses most of dgx-1's model margin |
| Cisco AIBOM | dgx-2 | 58 min, then 1 h 59 min (2026-11-16 04:22). A third run (11:22) was stopped at 2.5 h by the observability session's work | 1.3–1.8 GiB | Remote image scans (Jetson HA image) added in #85 |
| Cisco AIBOM | Pi | 13 min CPU | small | — |
| Cisco AIBOM | Jetson | not measurable: the journal only reaches back 4 h (§3.4) | 1.1–1.24 GiB (tool review) | #121 moves the Hermes checkouts to dgx-2 (**overlap: observability**) |
| Cisco AIBOM | CI | 110 s scan + 28 s install, on every PR **and** every push | — | §4.3 C3 |
| Lynis | all hosts | 37 s – 2 min 49 s CPU, weekly | 36–106 MB | Fine |

**Make AIBOM incremental and change-triggered:**

1. **Stagger the timers.** dgx-1 04:20, dgx-2 04:22 and the Pi's runs share the one-in-flight `cisco-aibom` key. Space them at least 1 h apart, or give each host its own key with the same limits.
2. **Honour 429s** in `cisco-aibom-fleet`: retry with `Retry-After` / backoff, with concurrency ≤ the key's `max_parallel_requests`. Otherwise every 429 is a lost analysis that runs again the next night.
3. **Skip unchanged targets.** Hash each code directory (`git rev-parse HEAD`, or a tree hash for non-git paths) and each image digest, and reuse yesterday's result when it is equal. Most nights nothing changes: in the last report, dgx-1's `added` was 0.
4. **Trigger on change.** Run a target after its deploy (the Ansible handler or an Argo CD post-sync hook), keep a weekly full run, and drop the nightly full run.
5. Together these should bring the nightly fleet scan from 1–2.5 h per Spark to minutes on most nights (e), and remove about 340 LLM 429s a day.

---

## 9. Power and thermals

- **No whole-system power metric for the Sparks.** `fleet_power_watts` exists only for the Jetson's rails (VDD_IN average 5 W, max 9 W). DCGM gives GPU power only:

  | Spark | GPU power average | Max | Note |
  |---|---|---|---|
  | dgx-1 | 10–27 W | 94 W | Busy |
  | dgx-2 | 3.6–7 W | 46 W | Idle |

  A smart plug or the UPS (architecture §17.3, not bought yet) is the way to measure idle draw.
- **Thermals.** dgx-1's `acpitz` runs hot under inference (median 58.8 °C, max 94.1 °C) and throttles briefly (87 s SW, 5.5 s HW since boot). dgx-2 maxed at 72 °C. Jetson ≤ 57.5 °C. Pi ≤ 75.5 °C, under its own 78 °C alert. Omarchy ≤ 62 °C.
- **What could idle down:**
  - **dgx-1 runs a full desktop** (`graphical.target`, GNOME + NVIDIA Sync, 1.26 GiB). Every host boots to `graphical.target`; dgx-2 has no desktop processes. If you don't use NVIDIA Sync or the desktop on dgx-1, `multi-user.target` frees 1.26 GiB. **[decision]**
  - dgx-2's GPU is idle almost all day. Moving the always-warm model there instead of dgx-1 (dgx-2 has 112 GiB available) would let dgx-1 take on-demand models. It is a placement question for the DGXMM session (P2.0, R4/R15), **[decision]**.
  - Nothing should be powered down: both Sparks are k3s servers and etcd members (decision 0005).

---

## 10. Ranked recommendations

**Impact:** H/M/L. **Effort:** S = under an hour, M = an evening, L = several sessions. **Risk:** L/M/H.
Marks: **QW** = quick win, **[D]** = needs your decision, **[WIP: x]** = overlaps work in progress by session x.

| Rank | Recommendation | Section | Impact | Effort | Risk | Mark | Saving (e = estimate) |
|---|---|---|---|---|---|---|---|
| 1 | **CI: drop the push-to-main run, 8 jobs → 2, path filters for docs-only and the AI scanners, pip cache** | §4.3 C1–C4 | H | S–M | L | QW | **−72 to −78 % of minutes**: about 23 → 5–6.5 min per merged PR; the Free quota goes from about 87 to about 300 PRs a month |
| 2 | **Quiet the RoboClaw control-center poller** (backoff, one line per state change) or stop the unit if unused | §3.2 N1 | H | S | L | QW [D] | **−2.1 GiB/day of logs** (38 %), Jetson CPU, journal |
| 3 | **DGXMM: reuse SSH connections to dgx-2** (`ControlMaster`/`ControlPersist` in `DGXMM_SSH_CONFIG`, or the HTTP probe) | §3.2 N2 | H | S | L | [WIP: DGXMM] | **−1.8 GiB/day**, −1.5 M journal lines/day; dgx-2's journal keeps weeks again |
| 4 | **`qwen3.8-27b` idle timeout 300 s → 3,600 s** (or always on) | §5.3 | H | S | L | [D] [WIP: DGXMM] | **−13 of 18 cold starts** (about −40 min of loading and −13 judge timeouts a day); memory unchanged in practice |
| 5 | **AIBOM: stagger the timers, honour 429s, skip unchanged targets, trigger on deploy** | §8, §5.2 | H | M | L | [WIP: observability] | dgx-1 back from 2 h 25 min to about 16 min or less; **−340 429s/day**; less nightly peak memory on the Sparks |
| 6 | **Memory guard rails on the Sparks**: earlyoom and gpu-oom-guard into Git; `k3s-server` on earlyoom's avoid list and the engines on `--prefer`; `FleetMemoryLow` on GB10 at MemAvailable < 12 GiB; `mem_limit` on LiteLLM, Phoenix, Loki, VictoriaMetrics, Grafana and Temporal | §1.3, §1.4, §3.6 | H | S–M | L | QW (the alert, the limits) [WIP: platform for LiteLLM] | Closes the incident's open follow-up; an alert that fires before the kill; no service can eat the model margin unseen |
| 7 | **Slim journald records in the host collector** (keep MESSAGE + 5 fields; drop `_CMDLINE` and the rest) and filter sshd VERBOSE chatter | §3.2 | M | S–M | L | QW | **−60–70 % of the remaining bytes** (−0.9 GiB/day from dgx-1's sshd alone); command lines out of Loki |
| 8 | **Alert thresholds**: GB10 `FleetHostHot` > 95 °C for 15 min plus throttle counters; `ObservabilityComponentDown` `for: 10m`; one push per symptom across Gatus and vmalert | §3.6, §2 | M | S | L | QW | **−45 pending episodes per 36 h**; fewer duplicate pushes per outage |
| 9 | **vLLM: `--gpu-memory-utilization` 0.48 → about 0.38–0.40** (KV use is 16 %), and scrape vLLM's metrics | §5.4, §3.5 | M | S | M | [WIP: DGXMM] | **+10–14 GiB** of headroom on dgx-1 (e) |
| 10 | **Spark traffic onto the cable**: dgx-1's OTLP to `10.100.136.2` (`host_vars`); later, the front-door upstreams for dgx-2 services; **lock dgx-2 to 5 GHz ch 149** (−64 dBm instead of −72/−74) until P0.11 | §6 | M | S | L–M | QW (OTLP) [D] (Wi-Fi) [WIP: platform] (front door) | Less Wi-Fi contention; dgx-2 link +8–10 dB (e) |
| 11 | **LiteLLM 1 worker per pod** in the k3s move (2 pods for HA) | §5.5 | M | S | L | [WIP: platform] | **−1.4 GiB** on the Sparks (e) |
| 12 | **Jetson journal on NVMe** (`Storage=persistent`, 500M cap) | §3.4 | M | S | L | QW | −150 MiB of RAM on the Jetson; history survives reboots |
| 13 | **Backups: decide P1.10.** If on, add Pocket ID, the MLflow and Temporal dumps, Grafana, etcd snapshots and CNPG; get repos off dgx-2; drop the retired front-door paths after 2026-11-22 | §7.1 | H (if a disk dies) | M | L | [D] | Closes the "Pocket ID lost = no one can sign in" gap |
| 14 | **Phoenix retention (30 days) and no tracing of the scanner keys** | §2 | M | S | L | QW | About −0.4 GB/day of disk growth; about −0.5 GiB RSS over time (e) |
| 15 | **Fix the Jetson's Tailscale DNS upstream** (SERVFAIL about 720/h) | §3.2 N6 | M | S | L | — | Real lookups stop failing; −31 k lines/day |
| 16 | **Jetson kube-router NFLOG failure** | §3.2 N4 | M (security) | M | M | [WIP: platform] | NetworkPolicy enforced on the Jetson; −100 k lines/day |
| 17 | **Docker log rotation** via per-stack `x-logging` now, `daemon.json` at the next planned Docker restart | §7.2 | L | S | L | [D] (code review #28) | Caps LiteLLM's about 44 MB/day |
| 18 | **Housekeeping**: prune images and build cache after the rollback dates; remove `dmm-qwen38-inference` and `sdd-check-nccl`; decide on duplicate and unused model weights | §7.3 | L | S | L | QW (images) [D] (models) | **about 84 GB** of disk; up to about 486 GB more for models |
| 19 | **Small hosts**: Pi Wi-Fi country (N7); Omarchy USB stick or a filesystem exclude (N5); stop Jetson iperf3 and SANE and Pi rpcbind; give Pi otelcol `GOMEMLIMIT` or a 320M cap (or the slim build, tool review #8) | §3.2, §2, §1.5 | L | S | L | QW ([D] timing for the Pi Wi-Fi) | −64 k lines/day; three fewer listeners; no collector OOM on the Pi |
| 20 | **Metrics hygiene**: exclude `veth*/cni*/flannel*/docker*/br-*` from hostmetrics; drop dcgm's `Hostname` label; trim Temporal histograms | §3.5 | L | S | L | QW | About −10–20 % of series, no churn per restart |
| 21 | **dgx-1 desktop**: `multi-user.target` if NVIDIA Sync and GNOME aren't used | §9 | L | S | L | [D] | −1.26 GiB on dgx-1 |
| 22 | **Right-size `ops-db` requests** (256 → 96 Mi) | §1.3 | L | S | L | [WIP: ambient agent] | Bookkeeping only |

### 10.1 Estimated savings, if all of the above are done

| Resource | Today | After | Saving |
|---|---|---|---|
| CI minutes per merged PR | about 23 | about 5–6.5 | **−72 to −78 %**. At this week's volume, about −2,350 per 37.8 h. At 10 PRs a day, about 7,000 → 2,300 a month (e) |
| Logs (Loki raw) | 5.4 GiB/day | about 0.3–0.7 GiB/day | **−4.7 to −5.1 GiB/day** |
| Journal lines | 4.67 M/day | about 0.5 M/day | about −89 % (e) |
| Steady RAM | — | — | **about −3.0 GiB**: LiteLLM workers −1.4, dgx-1 desktop −1.26 [D], Jetson journal −0.15, ops-db/Phoenix small. **Plus +10–14 GiB of model headroom on dgx-1** (vLLM KV, e) |
| Disk | — | — | **about 84 GB** of images and build cache now; up to about 486 GB of model weights [D]; Phoenix growth capped at about 13 GB |
| Model plane | 13 cold starts/day, 955 429s/day | about 4 cold starts/day, about 0 429s | −40 min loading/day, −13 judge timeouts/day |
| Alert noise | 45 FleetHostHot pending episodes and up to 2 pushes per outage | about 0 and 1 | — |

### 10.2 Needs your decision

1. RoboClaw control-center: fix its poller, or stop it (#2).
2. `qwen3.8-27b`: 1 h idle timeout or always on; and whether the warm model should live on dgx-2 (#4, §9).
3. Lock dgx-2's Wi-Fi to 5 GHz until P0.11 (#10).
4. Backups on or off (P1.10, decision 0002), and what to add (#13).
5. Docker log rotation approach (#17, code review #28).
6. Delete duplicate or unused model weights (#18).
7. The dgx-1 desktop and NVIDIA Sync (#21).
8. When to set the Pi's Wi-Fi country (robot docked) (#19).

### 10.3 Overlaps with work in progress

| Session | Items |
|---|---|
| Platform (LiteLLM and Pocket ID into k3s, Argo CD HA, Jetson NetworkPolicy) | #6 (LiteLLM limits), #10 (front-door upstreams), #11 (workers), #16 (NFLOG, worktree `fix/jetson-netpol-nflog`), §7.4 (spend-log cleanup at the CNPG move) |
| Ambient-agent build (Temporal mTLS, `ops`) | #22; Temporal is kept (§2); journal retention matters for its RCA inputs (§3.4) |
| Observability (AIBOM on dgx-2) | #5, #121 |
| DGXMM session | #3, #4, #9, P2.7 |

---

## 11. Method notes

- Queries ran from dgx-1. VictoriaMetrics, Loki and vmalert were reached through their container addresses on dgx-2 (they aren't published). LiteLLM's Postgres was queried through `docker exec … psql` with aggregates and key aliases only. DGXMM's SQLite was opened with `mode=ro`. Working files stayed in `~/infra-review-2026-11` on dgx-1.
- Secrets: no config values were printed. vLLM's arguments and environment were read with secret-looking values redacted. The restic error lines were checked to be redacted by restic itself.
- Billable CI minutes are recomputed from job timestamps (per-job round-up). The account's billing API needs a `user` scope that the CLI token doesn't have, so GitHub's own figure wasn't read.
- Everything marked (e) is an estimate. The rest was measured on 2026-11-16.
