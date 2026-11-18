#!/usr/bin/env bash
# Installs restart-safe Delta Demo FIRE protective-order watchdog (not an entry bot).
set -euo pipefail
set +x
umask 077
if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as your normal VM SSH user, not root." >&2; exit 1
fi
if ! command -v systemctl >/dev/null; then
  echo "systemd unavailable." >&2; exit 1
fi
PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
VM_USER="$(id -un)"
VM_GROUP="$(id -gn)"
VM_HOME="$HOME"
if [[ "$PROJECT" == *' '* || "$PROJECT" == *'%'* ||
      "$VM_HOME" == *' '* || "$VM_HOME" == *'%'* ]]; then
  echo "Unsupported special characters in paths." >&2; exit 1
fi
if [[ ! -r "$VM_HOME/.config/tradebot2/keys.env" ||
      ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "Protected credentials and installed virtualenv required." >&2; exit 1
fi
mkdir -p "$PROJECT/data"
chmod 700 "$PROJECT/data"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<EOF
[Unit]
Description=Tradebot 2.0 - Delta India Demo FIRE protection watchdog
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$VM_USER
Group=$VM_GROUP
Environment=HOME=$VM_HOME
WorkingDirectory=$PROJECT
ExecStart=/usr/bin/bash $PROJECT/ops/run_fire_watchdog.sh
Restart=always
RestartSec=10
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
SyslogIdentifier=tradebot2-fire-watchdog

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 0644 "$tmp" /etc/systemd/system/tradebot2-fire-watchdog.service
sudo systemctl daemon-reload
sudo systemctl enable --now tradebot2-fire-watchdog.service
sudo systemctl restart tradebot2-fire-watchdog.service
echo "FIRE protective-order watchdog installed (Delta India DEMO only)."
echo "It does NOT initiate trades or make paid AI requests."
sudo systemctl --no-pager status tradebot2-fire-watchdog.service
