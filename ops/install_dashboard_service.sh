#!/usr/bin/env bash
# One-time private browser dashboard systemd setup.
# Read-only HTTP server on 127.0.0.1:8765. Never expose to public internet.
set -euo pipefail
set +x
umask 077
if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run this as your normal VM SSH user (not root)." >&2
  exit 1
fi
if ! command -v systemctl >/dev/null; then
  echo "systemd unavailable." >&2
  exit 1
fi

PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
VM_USER="$(id -un)"
VM_GROUP="$(id -gn)"
VM_HOME="$HOME"
UNIT="tradebot2-dashboard.service"

if [[ "$PROJECT" == *' '* || "$PROJECT" == *'%'* ||
      "$VM_HOME" == *' '* || "$VM_HOME" == *'%'* ]]; then
  echo "Unsupported space/percent in VM file paths." >&2
  exit 1
fi
if [[ ! -r "$VM_HOME/.config/tradebot2/keys.env" ||
      ! -f "$PROJECT/src/tradebot/dashboard.py" ]]; then
  echo "First install recent Tradebot code and secure keys on this VM." >&2
  exit 1
fi
mkdir -p "$PROJECT/data"
chmod 700 "$PROJECT/data"

unit_file="$(mktemp)"
trap 'rm -f "$unit_file"' EXIT
cat > "$unit_file" <<EOF
[Unit]
Description=Tradebot 2.0 - private browser monitoring dashboard (read-only)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$VM_USER
Group=$VM_GROUP
Environment=HOME=$VM_HOME
WorkingDirectory=$PROJECT
ExecStart=/usr/bin/bash $PROJECT/ops/run_dashboard.sh
Restart=always
RestartSec=15
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
SyslogIdentifier=tradebot2-dashboard

[Install]
WantedBy=multi-user.target
EOF

sudo install -m 0644 "$unit_file" "/etc/systemd/system/$UNIT"
sudo systemctl daemon-reload
sudo systemctl enable "$UNIT"
sudo systemctl restart "$UNIT"

echo "Private read-only dashboard installed on VM loopback port 8765."
echo "Status: sudo systemctl status tradebot2-dashboard --no-pager"
echo "Local test: curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/"
echo "For viewing on a different phone, add Cloudflare Tunnel + Access or another authenticated tunnel."
echo "Do not open firewall port 8765 or use a public unauthenticated tunnel."
sudo systemctl status "$UNIT" --no-pager
