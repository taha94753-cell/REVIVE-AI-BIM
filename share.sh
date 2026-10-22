#!/usr/bin/env bash
# Gives the REVIVE running on this computer a temporary public https link (Cloudflare quick tunnel).
# Free, no account. Start ./run.sh first; the link (….trycloudflare.com) works while this runs.
command -v cloudflared >/dev/null || { echo "Install cloudflared first: brew install cloudflared (macOS) or see https://github.com/cloudflare/cloudflared/releases"; exit 1; }
exec cloudflared tunnel --url http://localhost:8000
