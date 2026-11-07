#!/usr/bin/env bash
# Create a private CA (P-256, 10 years) for OfflineBudget's home-network HTTPS.
# Usage: scripts/tls/make-ca.sh <out_dir>      (default: ~/.offlinebudget-ca)
# ca.key is AES-256 encrypted with a passphrase (prompted, or read from the file
# named by OB_CA_PASSFILE for non-interactive runs). Refuses to overwrite.
# The CA is constrained: it can sign only for df-macbookpro16.local and the
# fallback host, and cannot sign sub-CAs, so a leaked CA key cannot impersonate
# any other site on a phone that trusts it.
set -euo pipefail

out_dir="${1:-$HOME/.offlinebudget-ca}"
key="$out_dir/ca.key"
crt="$out_dir/ca.crt"

if [[ -e "$key" || -e "$crt" ]]; then
  echo "refusing to overwrite existing CA in $out_dir" >&2
  exit 1
fi

umask 077
mkdir -p "$out_dir"
chmod 700 "$out_dir"

pass_args=()
passin_args=()
if [[ -n "${OB_CA_PASSFILE:-}" ]]; then
  pass_args=(-pass "file:$OB_CA_PASSFILE")
  passin_args=(-passin "file:$OB_CA_PASSFILE")
fi

openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 \
  -aes-256-cbc ${pass_args[@]+"${pass_args[@]}"} -out "$key"
chmod 600 "$key"

openssl req -x509 -new -key "$key" ${passin_args[@]+"${passin_args[@]}"} \
  -sha256 -days 3650 -subj "/CN=OfflineBudget Home CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "nameConstraints=critical,permitted;DNS:df-macbookpro16.local,permitted;DNS:budget.thedigitaltrailhead.com" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" \
  -out "$crt"
chmod 644 "$crt"

echo "CA written to $out_dir"
echo "Expires: $(openssl x509 -in "$crt" -noout -enddate | cut -d= -f2)"
