#!/usr/bin/env bash
# Disable new FIRE Demo entries; do NOT stop existing protective-order watchdog.
set -euo pipefail
set +x
if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as normal SSH user." >&2; exit 1
fi
target=/etc/systemd/system/tradebot2-dashboard.service.d/fire-demo.conf
sudo rm -f "$target"
sudo systemctl daemon-reload
sudo systemctl restart tradebot2-dashboard
echo "New FIRE execution disabled. Existing broker positions/orders are NOT automatically cancelled."
echo "Keep tradebot2-fire-watchdog running until the exchange is verified flat."
