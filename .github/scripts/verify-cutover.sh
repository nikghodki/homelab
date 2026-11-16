#!/usr/bin/env bash
# P3.3 cutover, step 4 (runbooks/edge.md "Cutover"): is the tailnet on the in-cluster front door, and does every
# route still answer like the old door? Run it after the cutover PR is applied (Argo CD shows `edge` Synced).
#
#   verify-cutover.sh [-r DIR]
#
# On dgx-1 (from a checkout) it also checks the cluster side: kube-system's CoreDNS forwards nghodki.ai to edge-dns,
# the tailnet Services carry both Sparks' Tailscale IPs, Argo CD's Pocket ID sign-in redirects, Gatus is green.
# On a client (the MacBook Air, over Tailscale), stream the files from dgx-1 as for compare-front-doors.sh and pass
# -r: it then also checks name resolution through the client's own resolver (MagicDNS split DNS) end to end.
# Exit 1 on any failure. bash 3 compatible; needs curl, and dig or python3.
set -u
REPO=""
while getopts "r:" f; do case $f in r) REPO=$OPTARG ;; *) sed -n '2,12p' "$0"; exit 2 ;; esac; done
here=$(cd "$(dirname "$0")" && pwd)
[ -n "$REPO" ] || REPO=$(cd "$here/../.." && pwd)
cmp=$here/compare-front-doors.sh
names=$REPO/cluster/platform/edge/names.txt; [ -f "$names" ] || names=$REPO/names.txt
CA=$REPO/hosts/files/pki/web-ca.crt; [ -f "$CA" ] || CA=$REPO/web-ca.crt
DGX1_TS=100.65.137.82 DGX2_TS=100.124.175.23 VIP=192.168.86.11 DGX1_LAN=192.168.86.44
fail=0
ok()  { printf 'ok    %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*"; fail=1; }
q()   { bash "$cmp" -Q "$@"; }   # SERVER TYPE NAME -> "RCODE COUNT addr..."

echo "## dgx-1's Tailscale IP answers DNS from the cluster (tailnet view), not edge-dnsmasq"
for ts in $DGX1_TS $DGX2_TS; do
  a=$(q "$ts" A grafana.nghodki.ai)
  case "$a" in "NOERROR 1 $DGX1_TS"|"NOERROR 1 $DGX2_TS") ok "@$ts grafana A: ${a#NOERROR 1 }" ;;
    *) bad "@$ts grafana A: '$a' (want one Spark Tailscale IP; dnsmasq answers two addresses)" ;; esac
  a=$(q "$ts" AAAA grafana.nghodki.ai)
  if [ "$a" = "NOERROR 0" ]; then ok "@$ts grafana AAAA: NOERROR, empty"; else bad "@$ts AAAA: '$a'"; fi
  # The tailnet view refuses other zones; edge-dnsmasq would forward them.
  a=$(q "$ts" A example.com)
  if [ "${a%% *}" = REFUSED ]; then ok "@$ts example.com: REFUSED"; else bad "@$ts example.com: '$a' (dnsmasq still answering?)"; fi
done

echo; echo "## Every route on dgx-1's Tailscale IP vs the LAN VIP (the old door on dgx-1 is retired)"
if bash "$cmp" -r "$REPO" -n $DGX1_TS -o $VIP -v tailnet > /tmp/verify-cutover.$$ 2>&1; then
  ok "compare-front-doors: $(grep -c ' yes$' /tmp/verify-cutover.$$) rows the same"
else
  grep -E ' NO$|RESULT|NXDOMAIN' /tmp/verify-cutover.$$; bad "compare-front-doors differs (full output above)"
fi
rm -f /tmp/verify-cutover.$$

echo; echo "## The old door is stopped (edge-caddy, edge-dnsmasq, nginx-gateway on dgx-1, 2026-11-15)"
for port in 80 443; do
  if curl -s -o /dev/null -m 5 "http://$DGX1_LAN:$port/" 2>/dev/null || [ $? -ne 7 ]; then
    bad "$DGX1_LAN:$port answers (edge-caddy running again?)"; else ok "$DGX1_LAN:$port: connection refused"; fi
done
a=$(q $DGX1_LAN A grafana.nghodki.ai); case "$a" in NOERROR*) bad "@$DGX1_LAN DNS answers: '$a' (edge-dnsmasq?)" ;;
  *) ok "@$DGX1_LAN DNS: no answer ($a)" ;; esac

if [ -n "${REPO##"$(cd "$here/../.." && pwd)"}" ] || ! command -v kubectl >/dev/null; then
  echo; echo "## This client's own resolver (MagicDNS split DNS), end to end"
  while read -r name <&3; do
    r=$(curl -s -o /dev/null -m 20 --cacert "$CA" -w '%{http_code} %{remote_ip}' "https://$name.nghodki.ai/" 2>/dev/null)
    case "$r" in
      [1-4][0-9][0-9]" $DGX1_TS"|[1-4][0-9][0-9]" $DGX2_TS"|[1-4][0-9][0-9]" $VIP") ok "$name: $r" ;;
      *) bad "$name: '${r:-no answer}' (want a status < 500 from a Spark's Tailscale IP or the VIP)" ;;
    esac
  done 3< <(awk '!/^#/ && NF == 2 && $2 == "edge" {print $1}' "$names")
fi

if command -v kubectl >/dev/null; then
  export KUBECONFIG=${KUBECONFIG:-$HOME/.kube/config}
  echo; echo "## Cluster side (dgx-1)"
  a=$(q 10.43.0.10 A grafana.nghodki.ai)
  if [ "$a" = "NOERROR 1 $VIP" ]; then ok "kube-dns grafana A: $VIP (LAN view via 10.43.0.53)"; else bad "kube-dns grafana: '$a'"; fi
  a=$(q 10.43.0.10 AAAA id.nghodki.ai)
  if [ "$a" = "NOERROR 0" ]; then ok "kube-dns id AAAA: NOERROR, empty"; else bad "kube-dns id AAAA: '$a'"; fi
  for s in edge-dns-tailnet edge-caddy-tailnet; do
    ips=$(kubectl -n edge get svc $s -o jsonpath='{.spec.externalIPs}')
    case "$ips" in *$DGX1_TS*$DGX2_TS*) ok "$s externalIPs $ips" ;; *) bad "$s externalIPs $ips" ;; esac
  done
  for app in edge cluster-dns kube-vip; do
    st=$(kubectl -n argocd get app $app -o jsonpath='{.status.sync.status}/{.status.health.status}')
    if [ "$st" = Synced/Healthy ]; then ok "app $app $st"; else bad "app $app $st"; fi
  done
  # Argo CD's server resolves id.nghodki.ai through kube-dns -> edge-dns -> the VIP; /auth/login must redirect there.
  r=$(curl -s -o /dev/null -m 20 --cacert "$CA" --resolve argocd.nghodki.ai:443:$VIP -w '%{http_code} %{redirect_url}' \
      https://argocd.nghodki.ai/auth/login | sed 's/?.*//')
  if [ "$r" = "303 https://id.nghodki.ai/authorize" ]; then ok "Argo CD sign-in redirects to Pocket ID"; else bad "Argo CD /auth/login: '$r'"; fi
  m=$(curl -s -m 10 http://192.168.86.49:8081/metrics | grep '^gatus_results_endpoint_success{' | grep -E 'group="(edge|web|observe|jobs|ml)"')
  down=$(printf '%s\n' "$m" | awk '$NF != 1' | sed 's/.*name="\([^"]*\)".*/\1/' | tr '\n' ',')
  if [ -n "$m" ] && [ -z "$down" ]; then ok "Gatus edge/web/observe/jobs/ml: all up"; else bad "Gatus down: ${down:-no metrics}"; fi
fi

echo; [ $fail = 0 ] && echo "CUTOVER VERIFIED" || echo "CUTOVER CHECKS FAILED"
exit $fail
