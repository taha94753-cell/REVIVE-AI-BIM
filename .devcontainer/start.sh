#!/usr/bin/env bash
# Starts REVIVE in the background when the codespace starts, and makes its link public so anyone can open it.
cd "$(dirname "$0")/.." || exit 1
if [ -n "$CODESPACE_NAME" ] && [ -n "$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN" ]; then
  # the phone QR code on the Live site sheet must point at the public address, not the container's
  export REVIVE_PUBLIC_URL="https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
fi
pkill -f "revive serve" 2>/dev/null
nohup python -m revive serve --host 0.0.0.0 --port 8000 > /tmp/revive.log 2>&1 &
# public link (no GitHub login needed to open it); harmless if not allowed
( sleep 8; gh codespace ports visibility 8000:public -c "$CODESPACE_NAME" >/dev/null 2>&1 ) &
echo "REVIVE is starting: ${REVIVE_PUBLIC_URL:-http://localhost:8000} (log: /tmp/revive.log)"
