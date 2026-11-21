#!/usr/bin/env bash
# Stage only an external HTTPS alert service; do NOT auto-start or enable.
# Never touch existing watchdog, collector, dashboard, FIRE, or risk databases.
set -euo pipefail
set +x
umask 077

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as the normal VM user, not root." >&2
  exit 2
fi

PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
USER_NAME="$(id -un)"
GROUP_NAME="$(id -gn)"
VM_HOME="$HOME"
ALERTS_FILE="$VM_HOME/.config/tradebot2/alerts.env"
UNIT="tradebot2-offhost-alerts.service"

if [[ "$PROJECT" == *' '* || "$PROJECT" == *'%'* ||
      "$VM_HOME" == *' '* || "$VM_HOME" == *'%'* ]]; then
  echo "Unsupported VM project path." >&2
  exit 2
fi
for unit in tradebot2-dashboard.service tradebot2-fire-watchdog.service tradebot2-equity-monitor.service; do
  if ! systemctl is-active --quiet "$unit"; then
    echo "Refused: prerequisite service is not active." >&2
    exit 2
  fi
done
if [[ ! -f "$ALERTS_FILE" || -L "$ALERTS_FILE" ||
      ! -r "$ALERTS_FILE" || "$(stat -c %a "$ALERTS_FILE")" != 600 ]]; then
  echo "Refused: alerts.env must exist, be readable, and have mode 600." >&2
  exit 2
fi
if [[ ! -f "$PROJECT/src/tradebot/offhost_alerts.py" ||
      ! -x "$PROJECT/.venv/bin/python" ||
      ! -f "$PROJECT/data/fire-monitoring.sqlite" ]]; then
  echo "Refused: deployed monitoring project/evidence unavailable." >&2
  exit 2
fi

# The alert setup checks are read-only and require two operator-provided
# public HTTPS destinations, not live broker keys.
set -a
# shellcheck disable=SC1090
source "$ALERTS_FILE"
set +a
unset PYTHONHOME PYTHONUSERBASE DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET TB_API_KEY
export PYTHONPATH="$PROJECT/src"
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1
export ENABLE_DEMO_ORDERS=false
"$PROJECT/.venv/bin/python" -m tradebot.offhost_alerts \
  --data-dir "$PROJECT/data" --check

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<EOF
[Unit]
Description=Tradebot 2.0 - off-machine safety incident relay (no orders)
After=network-online.target tradebot2-equity-monitor.service
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
Group=$GROUP_NAME
Environment=HOME=$VM_HOME
WorkingDirectory=$PROJECT
ExecStart=/usr/bin/bash $PROJECT/ops/run_offhost_alerts.sh
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
SyslogIdentifier=tradebot2-offhost-alerts

[Install]
WantedBy=multi-user.target
EOF

sudo install -m 0644 "$tmp" "/etc/systemd/system/$UNIT"
sudo systemctl daemon-reload
echo "External relay unit STAGED ONLY. It is NOT enabled or running."
echo "Configure/test external receiver, then activate in a separate supervised step."
echo "No FIRE, broker, watchdog, collector or dashboard changes were made."
