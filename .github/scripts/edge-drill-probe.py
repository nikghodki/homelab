#!/usr/bin/env python3
"""Front-door drill probe (runbooks/edge.md "Failover drill").

  edge-drill-probe.py SECONDS CSV

Run it on the Pi: a LAN client that is not a k3s node (so the VIP really goes through ARP) and a tailnet client that
resolves through MagicDNS. One thread per probe, ~2 Hz each; one CSV line per attempt: epoch,probe,ok,detail.
  dns_lan / dns_magic / dns_ts_<spark>   grafana.nghodki.ai A from the VIP, MagicDNS, each Spark's Tailscale IP
  lan_<route> / ts_<route>               HTTPS through the VIP (--resolve) / by name over the tailnet
Routes: model (LiteLLM health), ha, webui, ops and dgxmanager (signed out: 302 to Pocket ID), auth (edge-auth /ping).
curl: 5 s connect timeout, 8 s in total; the web CA must be in the system trust store (role homelab_ca)."""
import socket, struct, subprocess, sys, threading, time, random
DUR = float(sys.argv[1]); OUT = open(sys.argv[2], "a", buffering=1)
VIP = "192.168.86.11"; TS = {"dgx-1": "100.65.137.82", "dgx-2": "100.124.175.23"}
lock = threading.Lock()
def log(p, ok, d):
    with lock: OUT.write(f"{time.time():.2f},{p},{int(ok)},{d}\n")
def dns(server, name="grafana.nghodki.ai", timeout=1.0):
    q = struct.pack(">HHHHHH", random.randint(0, 65535), 0x0100, 1, 0, 0, 0)
    q += b"".join(bytes([len(x)]) + x.encode() for x in name.split(".")) + b"\0" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(timeout)
    try:
        s.sendto(q, (server, 53)); r = s.recv(512)
        an = struct.unpack(">H", r[6:8])[0]
        if (r[3] & 0xF) != 0 or an == 0: return None, f"rcode{r[3] & 0xF}"
        i = 12 + len(q) - 12            # skip header + question (same as ours)
        while True:                      # walk answers, return the first A
            i += 2 if r[i] & 0xC0 == 0xC0 else (r.index(b"\0", i) + 1 - i)
            t, _, _, ln = struct.unpack(">HHIH", r[i:i + 10]); i += 10
            if t == 1: return socket.inet_ntoa(r[i:i + 4]), "ok"
            i += ln
    except Exception as e: return None, type(e).__name__
    finally: s.close()
ROUTES = {"model": ("/health/liveliness", "200"), "ha": ("/", "200"), "webui": ("/", "200"),
          "ops": ("/", "302"), "dgxmanager": ("/", "302"), "auth": ("/ping", "200")}
def http(name, lan):
    path, want = ROUTES[name]; host = f"{name}.nghodki.ai"
    cmd = ["curl", "-s", "-o", "/dev/null", "-m", "8", "--connect-timeout", "5",
           "-w", "%{http_code} %{remote_ip} %{time_total} %{redirect_url}"]
    if lan: cmd += ["--resolve", f"{host}:443:{VIP}"]
    out = subprocess.run(cmd + [f"https://{host}{path}"], capture_output=True, text=True).stdout.split(" ")
    code = out[0]; ok = code == want and (want != "302" or "id.nghodki.ai/authorize" in (out[3] if len(out) > 3 else ""))
    return ok, f"{code} {out[1] if len(out)>1 else ''} {out[2] if len(out)>2 else ''}"
def loop(p, fn):
    end = time.time() + DUR
    while time.time() < end:
        t = time.time(); ok, d = fn(); log(p, ok, d); time.sleep(max(0, 0.5 - (time.time() - t)))
def dnsprobe(server, want):
    def f():
        a, d = dns(server, timeout=2.0)
        return (a is not None and a.startswith(want)), f"{a} {d}"
    return f
probes = {"dns_lan": dnsprobe(VIP, "192.168.86.11"), "dns_magic": dnsprobe("100.100.100.100", "100."),
          "dns_ts_dgx-1": dnsprobe(TS["dgx-1"], "100."), "dns_ts_dgx-2": dnsprobe(TS["dgx-2"], "100.")}
for r in ROUTES:
    probes[f"lan_{r}"] = (lambda r=r: http(r, True)); probes[f"ts_{r}"] = (lambda r=r: http(r, False))
ts = [threading.Thread(target=loop, args=(p, f), daemon=True) for p, f in probes.items()]
[t.start() for t in ts]; [t.join() for t in ts]
