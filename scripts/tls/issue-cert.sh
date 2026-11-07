#!/usr/bin/env bash
# Issue a server certificate (825 days) signed by the private CA.
# Usage: scripts/tls/issue-cert.sh <ca_dir> <hostname> <out_dir>
#   (defaults: ~/.offlinebudget-ca, required hostname, ssl)
# Needs the CA passphrase (prompted, or OB_CA_PASSFILE). Refuses to overwrite,
# unless --renew is given: then the existing pair is moved to
# <out_dir>/server.<timestamp>.bak.{crt,key} first.
set -euo pipefail

renew=0
args=()
for a in "$@"; do
  if [[ "$a" == "--renew" ]]; then renew=1; else args+=("$a"); fi
done
set -- ${args[@]+"${args[@]}"}

ca_dir="${1:-$HOME/.offlinebudget-ca}"
host="${2:-}"
out_dir="${3:-ssl}"

if [[ -z "$host" ]]; then
  echo "usage: $0 <ca_dir> <hostname> <out_dir>" >&2
  exit 2
fi
if [[ ! "$host" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  echo "invalid hostname: $host" >&2
  exit 2
fi
if [[ ! -f "$ca_dir/ca.key" || ! -f "$ca_dir/ca.crt" ]]; then
  echo "no CA found in $ca_dir (run make-ca.sh first)" >&2
  exit 1
fi
if [[ $renew -eq 0 ]] && [[ -e "$out_dir/server.key" || -e "$out_dir/server.crt" ]]; then
  echo "refusing to overwrite existing certificate in $out_dir" >&2
  exit 1
fi

umask 077
mkdir -p "$out_dir"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

passin_args=()
if [[ -n "${OB_CA_PASSFILE:-}" ]]; then
  passin_args=(-passin "file:$OB_CA_PASSFILE")
fi

openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$work/server.key"
chmod 600 "$work/server.key"

openssl req -new -key "$work/server.key" -subj "/CN=$host" -out "$work/server.csr"

cat > "$work/ext.cnf" <<EXT
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=serverAuth
subjectAltName=DNS:$host
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid
EXT

openssl x509 -req -in "$work/server.csr" \
  -CA "$ca_dir/ca.crt" -CAkey "$ca_dir/ca.key" ${passin_args[@]+"${passin_args[@]}"} \
  -set_serial "0x$(openssl rand -hex 16)" -sha256 -days 825 \
  -extfile "$work/ext.cnf" -out "$work/server.crt"
chmod 644 "$work/server.crt"

# New pair is complete and signed; only now touch out_dir.
if [[ $renew -eq 1 ]]; then
  stamp="$(date +%Y%m%d-%H%M%S)"
  for ext in crt key; do
    if [[ -e "$out_dir/server.$ext" ]]; then
      mv "$out_dir/server.$ext" "$out_dir/server.$stamp.bak.$ext"
    fi
  done
  echo "Existing certificate moved to $out_dir/server.$stamp.bak.*"
fi
mv "$work/server.key" "$out_dir/server.key"
mv "$work/server.crt" "$out_dir/server.crt"

echo "Certificate for $host written to $out_dir"
echo "Expires: $(openssl x509 -in "$out_dir/server.crt" -noout -enddate | cut -d= -f2)"
