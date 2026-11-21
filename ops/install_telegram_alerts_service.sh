#!/usr/bin/env bash
# Install systemd unit only. Does not enable, start, restart or send Telegram.
set -euo pipefail
set +x
umask 077

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as the normal VM SSH user, not root." >&2
  exit 2
fi
PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
VM_HOME="$HOME"
VM_USER="$(id -un)"
VM_GROUP="$(id -gn)"
TOKEN_FILE="$HOME/.config/tradebot2/telegram.env"
UNIT="tradebot2-telegram-alerts.service"

if [[ "$PROJECT" == *' '* || "$PROJECT" == *'%'* ||
      "$VM_HOME" == *' '* || "$VM_HOME" == *'%'* ]]; then
  echo "Refused: unsupported paths." >&2
  exit 2
fi
for service in tradebot2-dashboard.service tradebot2-fire-watchdog.service tradebot2-equity-monitor.service; do
  if ! systemctl is-active --quiet "$service"; then
    echo "Refused: protected service inactive." >&2
    exit 2
  fi
done
if [[ ! -f "$TOKEN_FILE" || -L "$TOKEN_FILE" || ! -r "$TOKEN_FILE" ||
      "$(stat -c %a "$TOKEN_FILE")" != 600 ||
      ! -f "$PROJECT/src/tradebot/telegram_alerts.py" ||
      ! -f "$PROJECT/data/fire-monitoring.sqlite" ||
      ! -f "$PROJECT/data/fire-telegram-delivery.sqlite" ||
      ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "Refused: Telegram config, explicit baseline or monitoring evidence missing." >&2
  exit 2
fi

# Source only Telegram secrets; never read the exchange credential file.
set -a
# shellcheck disable=SC1090
source "$TOKEN_FILE"
set +a
unset PYTHONHOME PYTHONUSERBASE DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET TB_API_KEY
export PYTHONPATH="$PROJECT/src"
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
"$PROJECT/.venv/bin/python" -m tradebot.telegram_alerts \
  --data-dir "$PROJECT/data" --check

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<EOF
[Unit]
Description=Tradebot 2.0 - Telegram safety notifications (no orders)
After=network-online.target tradebot2-equity-monitor.service
Wants=network-online.target

[Service]
Type=simple
User=$VM_USER
Group=$VM_GROUP
Environment=HOME=$VM_HOME
WorkingDirectory=$PROJECT
ExecStart=/usr/bin/bash $PROJECT/ops/run_telegram_alerts.sh
Restart=on-failure
RestartSec=20
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
StandardOutput=journal
StandardError=journal
SyslogIdentifier=tradebot2-telegram-alerts

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 0644 "$tmp" "/etc/systemd/system/$UNIT"
sudo systemctl daemon-reload
echo "TELEGRAM UNIT STAGED ONLY; NOT STARTED OR ENABLED"
echo "No FIRE or broker orders; original three services untouched."
