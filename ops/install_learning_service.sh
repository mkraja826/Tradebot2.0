#!/usr/bin/env bash
# Optional user-installed, read-only 24/7 Kimi learning service.
# Default: broker observations only, zero paid model completions.
set -euo pipefail
set +x
umask 077

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as normal VM SSH user, never root." >&2
  exit 1
fi
if ! command -v systemctl >/dev/null; then
  echo "Learning service requires systemd." >&2
  exit 1
fi
PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
VM_USER="$(id -un)"
VM_GROUP="$(id -gn)"
VM_HOME="$HOME"
UNIT="tradebot2-learning.service"
PAID="${TRADEBOT_KIMI_PAID_REVIEWS:-false}"
if [[ "$PAID" != "false" && "$PAID" != "true" ]]; then
  echo "TRADEBOT_KIMI_PAID_REVIEWS must be true or false." >&2
  exit 1
fi
if [[ "$PROJECT" == *' '* || "$PROJECT" == *'%'* ||
      "$VM_HOME" == *' '* || "$VM_HOME" == *'%'* ]]; then
  echo "Unsupported VM path for systemd." >&2
  exit 1
fi
if [[ ! -r "$VM_HOME/.config/tradebot2/keys.env" ||
      ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "Install local Python and private credentials before learning service." >&2
  exit 1
fi
mkdir -p "$PROJECT/data"
chmod 700 "$PROJECT/data"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<EOF
[Unit]
Description=Tradebot 2.0 - read-only BTC Demo position learning (optional)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$VM_USER
Group=$VM_GROUP
Environment=HOME=$VM_HOME
Environment=TRADEBOT_KIMI_PAID_REVIEWS=$PAID
WorkingDirectory=$PROJECT
ExecStart=/usr/bin/bash $PROJECT/ops/run_learning.sh
Restart=always
RestartSec=30
TimeoutStopSec=90
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
SyslogIdentifier=tradebot2-learning

[Install]
WantedBy=multi-user.target
EOF

sudo install -m 0644 "$tmp" "/etc/systemd/system/$UNIT"
sudo systemctl daemon-reload
sudo systemctl enable "$UNIT"
sudo systemctl restart "$UNIT"
echo "Learning watcher installed. Delta India Demo READ ONLY; orders are never sent."
echo "Paid Kimi reviews: $PAID"
echo "Kimi may request model credits only after a verified open-position observation."
echo "Check: sudo systemctl status tradebot2-learning --no-pager"
echo "Logs: sudo journalctl -u tradebot2-learning -n 25 --no-pager"
sudo systemctl --no-pager status "$UNIT"
