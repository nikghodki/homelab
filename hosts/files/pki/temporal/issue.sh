#!/usr/bin/env bash
# Temporal CA and certificates (runbooks/temporal.md, "mTLS and authorization"). Run on dgx-1 from the repo root.
#   issue.sh ca                          new Temporal CA (refuses if one exists); key -> pki_temporal_ca_key
#   issue.sh server                      frontend certificate (SAN temporal, localhost, 192.168.86.36, 127.0.0.1)
#   issue.sh client <name> <role>...     client certificate; roles: system:<r> or ns:<namespace>:<r>, r = reader|writer|admin
# Certificates go to hosts/files/pki/temporal/<name>.crt (public), keys into secrets/pki.enc.yaml as
# pki_temporal_<name>_key (dashes become underscores). Keys exist unencrypted only in a private temp dir that is
# removed on exit; nothing is printed but the certificate summary.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
command -v sops >/dev/null || { echo "sops not on PATH (~/.local/bin)" >&2; exit 1; }
DIR=hosts/files/pki/temporal
SOPS_FILE=secrets/pki.enc.yaml
DAYS_CA=3650
DAYS_LEAF=730
tmp=$(mktemp -d); chmod 700 "$tmp"; trap 'rm -rf "$tmp"' EXIT

sops_key() { printf 'pki_temporal_%s_key' "${1//-/_}"; }
has_key() { sops -d --extract "[\"$1\"]" "$SOPS_FILE" >/dev/null 2>&1; }
store_key() {  # $1 = sops key name, $2 = PEM file
  python3 -c 'import json,sys; print(json.dumps(open(sys.argv[1]).read()))' "$2" \
    | sops set --value-stdin "$SOPS_FILE" "[\"$1\"]"
}
ca_key() { sops -d --extract '["pki_temporal_ca_key"]' "$SOPS_FILE" > "$tmp/ca.key"; }

case "${1:-}" in
  ca)
    if has_key pki_temporal_ca_key || [ -e "$DIR/ca.crt" ]; then echo "a Temporal CA exists already" >&2; exit 1; fi
    openssl ecparam -name prime256v1 -genkey -noout -out "$tmp/ca.key"
    openssl req -x509 -new -key "$tmp/ca.key" -sha256 -days "$DAYS_CA" -out "$tmp/out.crt" \
      -subj "/O=nikghodki homelab/CN=homelab Temporal CA" \
      -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
      -addext "keyUsage=critical,keyCertSign,cRLSign" \
      -addext "subjectKeyIdentifier=hash"
    store_key pki_temporal_ca_key "$tmp/ca.key"
    name=ca
    ;;
  server)
    name=server
    ca_key
    openssl ecparam -name prime256v1 -genkey -noout -out "$tmp/leaf.key"
    openssl req -new -key "$tmp/leaf.key" -subj "/O=nikghodki homelab/CN=temporal-frontend" -out "$tmp/leaf.csr"
    printf '%s\n' "basicConstraints=critical,CA:FALSE" "keyUsage=critical,digitalSignature" \
      "extendedKeyUsage=serverAuth" "subjectKeyIdentifier=hash" "authorityKeyIdentifier=keyid" \
      "subjectAltName=DNS:temporal,DNS:localhost,IP:192.168.86.36,IP:127.0.0.1" > "$tmp/ext"
    openssl x509 -req -in "$tmp/leaf.csr" -CA "$DIR/ca.crt" -CAkey "$tmp/ca.key" -CAcreateserial -CAserial "$tmp/serial" \
      -days "$DAYS_LEAF" -sha256 -extfile "$tmp/ext" -out "$tmp/out.crt"
    store_key "$(sops_key server)" "$tmp/leaf.key"
    ;;
  client)
    name=${2:?client name}; shift 2
    [[ "$name" =~ ^[a-z0-9-]{1,40}$ ]] || { echo "bad name: $name" >&2; exit 1; }
    [ $# -gt 0 ] || { echo "at least one role" >&2; exit 1; }
    san=""
    for r in "$@"; do
      [[ "$r" =~ ^(system:(reader|writer|admin)|ns:[a-z0-9-]{1,63}:(reader|writer|admin))$ ]] || { echo "bad role: $r" >&2; exit 1; }
      san+="${san:+,}URI:urn:homelab:temporal:$r"
    done
    ca_key
    openssl ecparam -name prime256v1 -genkey -noout -out "$tmp/leaf.key"
    openssl req -new -key "$tmp/leaf.key" -subj "/O=nikghodki homelab/CN=temporal-$name" -out "$tmp/leaf.csr"
    printf '%s\n' "basicConstraints=critical,CA:FALSE" "keyUsage=critical,digitalSignature" \
      "extendedKeyUsage=clientAuth" "subjectKeyIdentifier=hash" "authorityKeyIdentifier=keyid" \
      "subjectAltName=$san" > "$tmp/ext"
    openssl x509 -req -in "$tmp/leaf.csr" -CA "$DIR/ca.crt" -CAkey "$tmp/ca.key" -CAcreateserial -CAserial "$tmp/serial" \
      -days "$DAYS_LEAF" -sha256 -extfile "$tmp/ext" -out "$tmp/out.crt"
    store_key "$(sops_key "$name")" "$tmp/leaf.key"
    ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
mv "$tmp/out.crt" "$DIR/$name.crt"
openssl x509 -in "$DIR/$name.crt" -noout -subject -enddate -ext subjectAltName,extendedKeyUsage 2>/dev/null | sed 's/^/  /'
