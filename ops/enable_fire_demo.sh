#!/usr/bin/env bash
# Explicit operator opt-in to the GPT-6 FIRE *Delta India Demo only* POST.
# Requires independent watchdog already active; never uses production URL.
set -euo pipefail
set +x
umask 077
if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as normal SSH user, not as root." >&2; exit 1
fi
if [[ "${TRADEBOT_CONFIRM_FIRE_DEMO:-}" != "YES-DELTA-DEMO" ]]; then
  echo "Set TRADEBOT_CONFIRM_FIRE_DEMO=YES-DELTA-DEMO to activate." >&2
  exit 1
fi
if [[ "$(sudo systemctl is-active tradebot2-fire-watchdog)" != "active" ]]; then
  echo "Install/start the independent FIRE watchdog first." >&2; exit 1
fi
if [[ "$(sudo systemctl is-active tradebot2-dashboard)" != "active" ]]; then
  echo "Private dashboard must be active first." >&2; exit 1
fi
# Refuse to enable real POSTs unless the dashboard already has its
# authenticated Cloudflare hostname configured (never open VM firewall).
EXISTING_ENV="$(sudo systemctl show -p Environment --value tradebot2-dashboard)"
if [[ ! "$EXISTING_ENV" =~ TRADEBOT_DASHBOARD_ALLOWED_HOST=[a-z0-9][a-z0-9.-]+ ]]; then
  echo "Dashboard lacks a configured Access-protected hostname." >&2
  echo "Do not use direct public IP or open dashboard port 8765." >&2
  exit 1
fi
dropin=/etc/systemd/system/tradebot2-dashboard.service.d
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<EOF
[Service]
Environment=TRADEBOT_FIRE_DEMO_EXECUTION=true
Environment=TRADEBOT_FIRE_MAX_CONTRACTS=1
EOF
sudo mkdir -p "$dropin"
sudo install -m 0644 "$tmp" "$dropin/fire-demo.conf"
sudo systemctl daemon-reload
sudo systemctl restart tradebot2-dashboard
echo "GPT-6 FIRE is now eligible to submit DEMO BTCUSD order + attached SL/TP."
echo "Demo pilot max 1 contract. Watchdog must remain active. Existing browser Access policy must remain enforced."
echo "Disable NEW FIRE requests: bash ops/disable_fire_demo.sh"
curl --fail --silent http://127.0.0.1:8765/api/fire || true
echo
