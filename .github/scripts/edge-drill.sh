#!/usr/bin/env bash
# Front-door failover drill (runbooks/edge.md "Failover drill"). Run on dgx-1 from a checkout.
#
#   edge-drill.sh fail SPARK       take SPARK's front-door path away, as if the Spark had died (not a reboot)
#   edge-drill.sh restore SPARK    undo it
#   edge-drill.sh monitor SECS LOG who holds the VIPs, node readiness, ready edge endpoints, once a second
#
# "fail": drop the VIPs (192.168.86.10/.11) arriving on SPARK's wlP9s9 and its Tailscale IP's :53/:80/:443 (raw
# table, so a dead peer blackholes instead of refusing), stop k3s and run k3s-killall.sh (kube-vip, Caddy, CoreDNS,
# edge-auth and every other pod on SPARK die without handing anything over), then remove the VIPs from wlP9s9 so
# SPARK stops answering ARP for them. Docker on SPARK is not touched. Never on both Sparks at once (etcd quorum is
# the other Spark plus the Jetson). "restore" starts k3s and removes the drops.
set -euo pipefail
export KUBECONFIG=${KUBECONFIG:-$HOME/.kube/config}
declare -A SSH=([dgx-1]="" [dgx-2]="ssh -n nikghodki-dgx-2@192.168.86.36")
declare -A TS=([dgx-1]=100.65.137.82 [dgx-2]=100.124.175.23)
declare -A API=([dgx-1]=https://192.168.86.36:6443 [dgx-2]=https://192.168.86.44:6443)   # the *other* Spark's API
VIPS="192.168.86.10 192.168.86.11"
on() { local s=$1; shift; if [ -z "${SSH[$s]}" ]; then bash -c "$*"; else ${SSH[$s]} "$*"; fi; }
rules() {  # $1 = -I or -D
  local r="" v; for v in $VIPS; do r+="sudo iptables -t raw $1 PREROUTING -i wlP9s9 -d $v -j DROP; "; done
  r+="sudo iptables -t raw $1 PREROUTING -i tailscale0 -d $2 -p tcp -m multiport --dports 53,80,443 -j DROP; "
  r+="sudo iptables -t raw $1 PREROUTING -i tailscale0 -d $2 -p udp --dport 53 -j DROP; "; echo "$r"
}
case "${1:-}" in
  fail)
    s=$2; [ -n "${TS[$s]:-}" ] || { echo "SPARK is dgx-1 or dgx-2"; exit 2; }
    other=$([ "$s" = dgx-1 ] && echo dgx-2 || echo dgx-1)
    kubectl --server "${API[$s]}" get node "$other" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' \
      | grep -qx True || { echo "$other is not Ready: refusing"; exit 1; }
    echo "$(date +%s.%N | cut -c1-13) FAIL $s"
    on "$s" "$(rules -I "${TS[$s]}") sudo systemctl stop k3s && sudo /usr/local/bin/k3s-killall.sh >/dev/null 2>&1;
      for v in $VIPS; do sudo ip addr del \$v/32 dev wlP9s9 2>/dev/null || true; done"
    echo "$(date +%s.%N | cut -c1-13) DOWN $s" ;;
  restore)
    s=$2; echo "$(date +%s.%N | cut -c1-13) RESTORE $s"
    on "$s" "sudo systemctl start k3s; $(rules -D "${TS[$s]}")"
    echo "$(date +%s.%N | cut -c1-13) STARTED $s" ;;
  monitor)
    end=$(( $(date +%s) + $2 )); exec >>"$3"
    while [ "$(date +%s)" -lt "$end" ]; do
      t=$(date +%s.%N | cut -c1-13)
      for s in dgx-1 dgx-2; do v=$(on "$s" "ip -br -4 addr show wlP9s9" | { grep -o '192\.168\.86\.1[01]' || true; } | tr '\n' ' '); echo "$t vip $s ${v:-none}"; done &
      for a in https://192.168.86.36:6443 https://192.168.86.44:6443; do
        o=$(timeout 3 kubectl --server $a --request-timeout 2s -n kube-system get lease plndr-cp-lock plndr-svcs-lock \
          -o jsonpath='{range .items[*]}{.spec.holderIdentity} {end}' 2>/dev/null) && {
          echo "$t lease $o"
          echo "$t nodes $(timeout 3 kubectl --server $a --request-timeout 2s get nodes -o jsonpath='{range .items[*]}{.metadata.name}={.status.conditions[?(@.type=="Ready")].status} {end}')"
          echo "$t eps $(timeout 3 kubectl --server $a --request-timeout 2s -n edge get endpointslices -o jsonpath='{range .items[*]}{.metadata.labels.kubernetes\.io/service-name}:{range .endpoints[?(@.conditions.ready==true)]}{.nodeName},{end} {end}')"
          echo "$t kdns $(timeout 3 kubectl --server $a --request-timeout 2s -n kube-system get endpointslices -l kubernetes.io/service-name=kube-dns -o jsonpath='{range .items[*].endpoints[?(@.conditions.ready==true)]}{.nodeName},{end}')"
          break; }
      done
      wait; sleep 1
    done ;;
  *) sed -n '2,13p' "$0"; exit 2 ;;
esac
