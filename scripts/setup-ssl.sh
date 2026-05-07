#!/usr/bin/env bash
# Generate a self-signed TLS certificate for HTTPS on LAN.
# Run once: ./scripts/setup-ssl.sh
# Then start normally: ./scripts/start.sh
# Your browser will show a certificate warning — click "Advanced → Proceed" once.

set -e
cd "$(dirname "$0")/.."

mkdir -p ssl

LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")

openssl req -x509 -newkey rsa:4096 \
  -keyout ssl/key.pem \
  -out ssl/cert.pem \
  -days 825 \
  -nodes \
  -subj "/CN=OfflineBudget" \
  -addext "subjectAltName=IP:127.0.0.1,IP:${LAN_IP},DNS:localhost"

echo ""
echo "  SSL certificate generated in ssl/"
echo "  LAN IP detected: ${LAN_IP}"
echo "  Certificate valid for 825 days."
echo ""
echo "  Run ./scripts/start.sh — the server will now use HTTPS."
echo "  On first access from each device, accept the self-signed certificate warning."
echo ""
