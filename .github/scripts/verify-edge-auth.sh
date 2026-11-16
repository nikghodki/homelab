#!/usr/bin/env bash
# Sign-in through the front door (decision 0011, runbooks/sign-in.md): every signed-in route sends a signed-out
# browser to Pocket ID with the one client (edge-auth) and the one callback (auth.nghodki.ai); the backends refuse
# requests that don't come through the door.
#
#   verify-edge-auth.sh [-n DOOR_IP] [-c CA_FILE] [-j COOKIE_JAR] [-B]
#
#   DOOR_IP     front door address (default 192.168.86.11, the edge VIP; a Spark's Tailscale IP for the tailnet path)
#   CA_FILE     web CA (default hosts/files/pki/web-ca.crt in this checkout)
#   COOKIE_JAR  a curl cookie jar with an _edge_auth session (after a sign-in): every route must then answer 200,
#               i.e. one session works for all of them
#   -B          skip the direct backend checks (they need the LAN: run them from a fleet host)
#
# ROUTES and GATES (see below) can be overridden from the environment, e.g. while only some apps are migrated.
# Exit 1 on any failure. bash 3 compatible; needs curl.
set -u
cd "$(dirname "$0")/../.." || exit 2
DOOR=192.168.86.11; CA=hosts/files/pki/web-ca.crt; JAR=""; BACKENDS=1
while getopts "n:c:j:B" f; do
  case $f in n) DOOR=$OPTARG ;; c) CA=$OPTARG ;; j) JAR=$OPTARG ;; B) BACKENDS="" ;; *) sed -n '2,17p' "$0"; exit 2 ;; esac
done
fail=0
ok() { printf 'ok    %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*"; fail=1; }
# probe SCHEME HOST PATH [curl args...] -> "CODE REDIRECT"
probe() {
  local scheme=$1 host=$2 path=$3; shift 3
  local port=443; [ "$scheme" = http ] && port=80
  curl -s -o /dev/null -m 15 --cacert "$CA" --resolve "$host:$port:$DOOR" -w '%{http_code} %{redirect_url}' "$@" \
    "$scheme://$host$path"
}

# The signed-in routes (Caddyfile `import signed_in`) and their backends with a path that needs no session there.
ROUTES=${ROUTES:-ops.nghodki.ai docs.nghodki.ai status.nghodki.ai mlflow.nghodki.ai}
# backend  path  expected-without-token
GATES=${GATES:-192.168.86.49:4180 / 403
192.168.86.49:4181 / 403
192.168.86.49:4181 /healthz 200
192.168.86.49:8081 / 403
192.168.86.49:8081 /health 200
192.168.86.36:4181 / 403
192.168.86.36:5000 / 401}

r=$(probe https auth.nghodki.ai /ping)
[ "${r%% *}" = 200 ] && ok "auth.nghodki.ai/ping 200 (edge-auth up)" || bad "auth.nghodki.ai/ping: '$r'"

for h in $ROUTES; do
  r=$(probe http "$h" /)
  [ "$r" = "308 https://$h/" ] && ok "$h http -> https" || bad "$h http: '$r' (want 308 https://$h/)"
  r=$(probe https "$h" /some/page?a=1\&b=2)
  code=${r%% *}; loc=${r#* }
  case "$code $loc" in
    "302 https://id.nghodki.ai/authorize?"*client_id=edge-auth*redirect_uri=https%3A%2F%2Fauth.nghodki.ai%2Foauth2%2Fcallback*)
      ok "$h signed out -> Pocket ID (client edge-auth, callback auth.nghodki.ai)" ;;
    *) bad "$h signed out: '$code ${loc%%\?*}...' (want 302 to Pocket ID with client_id=edge-auth)" ;;
  esac
  if [ -n "$JAR" ]; then
    r=$(probe https "$h" / -b "$JAR")
    [ "${r%% *}" = 200 ] && ok "$h with the session cookie: 200" || bad "$h with the session cookie: '$r'"
  fi
done

if [ -n "$BACKENDS" ]; then
  while read -r addr path want; do
    [ -n "$addr" ] || continue
    code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://$addr$path")
    if [ "$code" = "$want" ]; then ok "direct $addr$path without the door: $code"; else bad "direct $addr$path: $code (want $want)"; fi
  done <<< "$GATES"
fi

[ $fail = 0 ] && echo "EDGE AUTH VERIFIED" || { echo "EDGE AUTH: FAILURES"; exit 1; }
