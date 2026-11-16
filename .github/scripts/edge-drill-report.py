#!/usr/bin/env python3
"""Summarise one front-door drill step (runbooks/edge.md "Failover drill").

  edge-drill-report.py DIR    DIR has probe.csv (edge-drill-probe.py), monitor.log and events.log (edge-drill.sh)

Prints, relative to the FAIL event: when the VIPs left/arrived, node readiness and endpoint changes, and for every
probe its failed windows (first..last failed attempt, how many attempts failed, a sample of what they got)."""
import collections, sys
d = sys.argv[1]
ev = {}
for line in open(f"{d}/events.log"):
    p = line.split()
    if len(p) >= 2 and p[1] in ("FAIL", "DOWN", "RESTORE", "STARTED"): ev[p[1]] = float(p[0])
t0 = ev["FAIL"]; rel = lambda t: f"{t - t0:+7.1f}s"
print("events:", ", ".join(f"{k} {rel(v)}" for k, v in ev.items()))
last = {}
for line in open(f"{d}/monitor.log"):
    t, kind, rest = line.split(" ", 2); t = float(t); rest = rest.strip()
    key = kind + (" " + rest.split()[0] if kind == "vip" else "")
    if last.get(key) != rest:
        if key in last: print(f"  {rel(t)} {kind:5} {rest}")
        last[key] = rest
rows = collections.defaultdict(list)
for line in open(f"{d}/probe.csv"):
    t, p, ok, det = line.rstrip("\n").split(",", 3); rows[p].append((float(t), ok == "1", det))
print("probe failures (window: first..last failed attempt; n failed/attempts in window):")
for p in sorted(rows):
    r = rows[p]; wins = []; cur = None
    for i, (t, ok, det) in enumerate(r):
        if not ok:
            if cur is None: cur = [t, t, 0, det, r[i - 1][0] if i else t]
            cur[1] = t; cur[2] += 1
        elif cur is not None:
            cur.append(t); wins.append(cur); cur = None
    if cur is not None: cur.append(None); wins.append(cur)
    tot = f"{sum(not ok for _, ok, _ in r)}/{len(r)} failed"
    if not wins: print(f"  {p:16} ok ({len(r)} attempts)"); continue
    for a, b, n, det, prev_ok, next_ok in wins:
        gap = f"outage {next_ok - prev_ok:.1f}s" if next_ok else "still failing at the end"
        print(f"  {p:16} {rel(a)}..{rel(b)} {n} failed, {gap}; e.g. '{det}' [{tot}]")
