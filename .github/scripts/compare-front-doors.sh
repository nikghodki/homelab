#!/usr/bin/env bash
# Compare two addresses of the front door, without touching clients: every request pins the address with
# curl --resolve, every query names the server (runbooks/edge.md). Since the old door on dgx-1 (edge-caddy,
# edge-dnsmasq, nginx-gateway) was stopped on 2026-11-15, the reference is another address of the in-cluster door
# (LAN VIP vs a Tailscale IP); with the old door restored from its backup, pass -o 192.168.86.44 to compare with it.
#
#   compare-front-doors.sh [-n NEW_IP] [-o OLD_IP] [-v lan|tailnet] [-d DNS_IP] [-c CA_FILE] [-r REPO]
#
#   NEW_IP  front door under test (default 192.168.86.11, the edge VIP; a Spark's Tailscale IP for the tailnet path)
#   OLD_IP  reference (default 100.124.175.23, the door on dgx-2's Tailscale IP)
#   view    which generated zone the DNS answers must match: lan (default) or tailnet (either Spark's tailnet zone:
#           the replica that answers names its own Spark)
#   DNS_IP  new DNS server (default NEW_IP)
#   CA      web CA (default REPO/hosts/files/pki/web-ca.crt); REPO defaults to this checkout
#
# Prints a table (HTTP and HTTPS status code plus the redirect target without its query string, old vs new, per
# *.nghodki.ai route, plus the model plane's paths: LiteLLM, DGXMM, the door by IP) and the DNS results (A matches the zone, AAAA is NOERROR with no answer, an unknown name is
# NXDOMAIN). Exit 1 on any difference. Runs with bash 3 (macOS) and needs curl, and dig or python3. On a host
# without the repo, copy names.txt, the coredns/*.db zones and web-ca.crt into one directory and pass it as -r.
set -u
NEW=192.168.86.11 OLD=100.124.175.23 VIEW=lan DNS="" CA="" REPO="" QUERY=0
while getopts "n:o:v:d:c:r:Q" f; do
  case $f in n) NEW=$OPTARG ;; o) OLD=$OPTARG ;; v) VIEW=$OPTARG ;; d) DNS=$OPTARG ;; c) CA=$OPTARG ;; r) REPO=$OPTARG ;;
    Q) QUERY=1 ;; *) sed -n '2,16p' "$0"; exit 2 ;; esac
done
shift $((OPTIND - 1))
[ -n "$REPO" ] || REPO=$(cd "$(dirname "$0")/../.." && pwd)
[ -n "$DNS" ] || DNS=$NEW
zdir=$REPO/cluster/platform/edge/coredns names=$REPO/cluster/platform/edge/names.txt
[ -f "$names" ] || { names=$REPO/names.txt; zdir=$REPO; }
[ -n "$CA" ] || CA=$REPO/hosts/files/pki/web-ca.crt
[ -f "$CA" ] || CA=$REPO/web-ca.crt
case $VIEW in lan) zones=$zdir/lan.db ;; tailnet) zones=$(ls "$zdir"/tailnet-*.db 2>/dev/null) ;; *) echo "bad view" >&2; exit 2 ;; esac
[ "$QUERY" = 1 ] || for f in "$names" $zones "$CA"; do [ -f "$f" ] || { echo "missing $f" >&2; exit 2; }; done
fail=0

# probe SCHEME HOST IP [PATH] -> "CODE [redirect target without query]" (OAuth state and PKCE values change every time)
probe() {
  local port=80; [ "$1" = https ] && port=443
  curl -s -o /dev/null -m 20 --cacert "$CA" --resolve "$2:$port:$3" -w '%{http_code} %{redirect_url}' "$1://$2${4:-/}" \
    2>/dev/null | sed 's/?.*//; s/ $//'
}
# The door by IP (no name): HTTP only (the cert has no IP SANs); the redirect target names the address, so drop it.
probe_ip() { curl -s -o /dev/null -m 20 -w '%{http_code}' "http://$1$2" 2>/dev/null; }

# q SERVER TYPE NAME -> "RCODE ANSWERCOUNT addr ..." (A/AAAA), with dig or, if there's none, python3 (stdlib).
q() {
  if command -v dig >/dev/null; then
    dig +time=3 +tries=2 @"$1" "$3" "$2" | awk -v t="$2" '
      /status:/ {s = $6; sub(",", "", s)}
      /ANSWER:/ {for (i = 1; i <= NF; i++) if ($i == "ANSWER:") {a = $(i + 1); sub(",", "", a)}}
      /^[^;]/ && $4 == t {ips = ips " " $5}
      END {print (s == "" ? "TIMEOUT" : s) " " (a == "" ? 0 : a) ips}'
  else
    python3 - "$1" "$2" "$3" <<'PYDNS'
import random, socket, struct, sys
server, qtype, name = sys.argv[1], {"A": 1, "AAAA": 28}[sys.argv[2]], sys.argv[3]
msg = struct.pack(">HHHHHH", random.randint(0, 65535), 0x0100, 1, 0, 0, 0)
msg += b"".join(bytes([len(l)]) + l.encode() for l in name.split(".")) + b"\0" + struct.pack(">HH", qtype, 1)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(3)
try:
    s.sendto(msg, (server, 53))
    r = s.recv(4096)
except OSError:
    print("TIMEOUT 0")
    sys.exit()
def skip(i):
    while True:
        if r[i] & 0xC0 == 0xC0:
            return i + 2
        if r[i] == 0:
            return i + 1
        i += r[i] + 1
rcode = {0: "NOERROR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}.get(r[3] & 15, str(r[3] & 15))
an = struct.unpack(">H", r[6:8])[0]
i, ips = skip(12) + 4, []
for _ in range(an):
    i = skip(i)
    t, _, _, ln = struct.unpack(">HHIH", r[i:i + 10])
    i += 10
    if t == 1:
        ips.append(socket.inet_ntoa(r[i:i + ln]))
    elif t == 28:
        ips.append(socket.inet_ntop(socket.AF_INET6, r[i:i + ln]))
    i += ln
print(rcode, an, *ips)
PYDNS
  fi
}

# `compare-front-doors.sh -Q SERVER TYPE NAME`: print one query's result and exit (used by verify-cutover.sh).
if [ "$QUERY" = 1 ]; then q "$@"; exit 0; fi

echo "## HTTP(S): old $OLD vs new $NEW"
printf '%-28s %-6s %-36s %-36s %s\n' name scheme old new same
for name in $(awk '!/^#/ && NF == 2 && $2 == "edge" {print $1}' "$names"); do
  host=$name.nghodki.ai
  for scheme in http https; do
    o=$(probe $scheme "$host" "$OLD"); n=$(probe $scheme "$host" "$NEW")
    same=yes; [ "$o" = "$n" ] || { same=NO; fail=1; }
    printf '%-28s %-6s %-36s %-36s %s\n' "$host" "$scheme" "${o:-error}" "${n:-error}" "$same"
  done
done

echo; echo "## Model plane paths: old $OLD vs new $NEW"
printf '%-50s %-6s %-36s %-36s %s\n' url scheme old new same
for hp in model:/health/liveliness model:/v1/models model:/v1 model:/dgxmm/ model:/dgxmm model:/dgxmm/ondemand/x \
          model:/tts/v1/x dgxmanager:/dgxmm/ dgxmanager:/v1/models ha:/manifest.json; do
  host=${hp%%:*}.nghodki.ai path=${hp#*:}
  for scheme in http https; do
    o=$(probe $scheme "$host" "$OLD" "$path"); n=$(probe $scheme "$host" "$NEW" "$path")
    o=${o//$OLD/ADDR} n=${n//$NEW/ADDR}
    same=yes; [ "$o" = "$n" ] || { same=NO; fail=1; }
    printf '%-50s %-6s %-36s %-36s %s\n' "$host$path" "$scheme" "${o:-error}" "${n:-error}" "$same"
  done
done
for path in / /v1/models /health/liveliness /dgxmm/; do
  o=$(probe_ip "$OLD" "$path"); n=$(probe_ip "$NEW" "$path")
  same=yes; [ "$o" = "$n" ] || { same=NO; fail=1; }
  printf '%-50s %-6s %-36s %-36s %s\n' "(by IP)$path" http "${o:-error}" "${n:-error}" "$same"
done

echo; echo "## DNS @$DNS ($VIEW view)"
printf '%-28s %-34s %-10s %s\n' name A AAAA ok
for name in $(awk '!/^#/ && NF == 2 {print $1}' "$names"); do
  host=$name.nghodki.ai
  got=$(q "$DNS" A "$host" | cut -s -d' ' -f3- | tr ' ' '\n' | grep . | sort | tr '\n' ' ')
  aaaa=$(q "$DNS" AAAA "$host" | awk '{print $1 "/" $2}')
  match=NO  # the answer must equal the A set of one of the view's zones
  for z in $zones; do
    [ "$got" = "$(awk -v n="$name" '$1 == n && $3 == "A" {print $4}' "$z" | sort | tr '\n' ' ')" ] && match=yes
  done
  ok=yes; { [ $match = yes ] && [ "$aaaa" = "NOERROR/0" ]; } || { ok=NO; fail=1; }
  printf '%-28s %-34s %-10s %s\n' "$host" "${got:-none}" "$aaaa" "$ok"
done
nx=$(q "$DNS" A no-such-name.nghodki.ai | cut -d' ' -f1)
echo "no-such-name.nghodki.ai: $nx (want NXDOMAIN)"; [ "$nx" = NXDOMAIN ] || fail=1

echo; [ $fail = 0 ] && echo "RESULT: same" || echo "RESULT: DIFFERENT"
exit $fail
