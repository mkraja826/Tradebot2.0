#!/usr/bin/env bash
# Install, enable and start a read-only Tradebot 2.0 Linux systemd service.
# Run as the normal SSH user: bash ops/install_observe_service.sh
# Does not copy/print keys or enable demo trading.
set -euo pipefail
set +x
umask 077

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as your normal VM SSH user, not root or with sudo." >&2
  exit 1
fi
if ! command -v systemctl >/dev/null; then
  echo "systemd isn't available on this host." >&2
  exit 1
fi

PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
VM_USER="$(id -un)"
VM_GROUP="$(id -gn)"
VM_HOME="$HOME"
UNIT_NAME="tradebot2-observe.service"
KEY_FILE="$VM_HOME/.config/tradebot2/keys.env"

# Reject paths that could be interpreted as systemd specifiers or whitespace.
if [[ "$PROJECT" == *' '* || "$PROJECT" == *'%'* ||
      "$VM_HOME" == *' '* || "$VM_HOME" == *'%'* ]]; then
  echo "VM path contains unsupported characters; stop without installing." >&2
  exit 1
fi

if [[ ! -r "$KEY_FILE" ]]; then
  echo "Private credentials file is missing; do not paste keys here." >&2
  exit 1
fi
if [[ ! -x "$PROJECT/.venv/bin/tradebot" ]]; then
  echo "First run: cd ~/Tradebot2.0 && source .venv/bin/activate && python -m pip install -e ." >&2
  exit 1
fi
mkdir -p "$PROJECT/data"
chmod 700 "$PROJECT/data"

tmp_unit="$(mktemp)"
trap 'rm -f "$tmp_unit"' EXIT

cat > "$tmp_unit" <<EOF
[Unit]
Description=Tradebot 2.0 - continuous read-only Delta India DEMO observer
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$VM_USER
Group=$VM_GROUP
Environment=HOME=$VM_HOME
WorkingDirectory=$PROJECT
ExecStart=/usr/bin/bash $PROJECT/ops/run_observe.sh
Restart=always
RestartSec=45
TimeoutStopSec=90
KillSignal=SIGTERM
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
SyslogIdentifier=tradebot2-observe

[Install]
WantedBy=multi-user.target
EOF

echo "Installing a 24/7 READ-ONLY service; demo order execution stays OFF."
sudo install -m 0644 "$tmp_unit" "/etc/systemd/system/$UNIT_NAME"
sudo systemctl daemon-reload
sudo systemctl enable --now "$UNIT_NAME"
# Restart on reinstallation to pick up repo changes.
sudo systemctl restart "$UNIT_NAME"

echo
echo "Service configured to auto-start on VM boot and restart after a crash."
echo "Observer mode: Delta India DEMO, NO order submission."
echo "Polling: 60 seconds. Model proposals: hourly while NYSE entry window is open."
echo "Check: sudo systemctl status tradebot2-observe --no-pager"
echo "Logs: sudo journalctl -u tradebot2-observe -n 20 --no-pager"
echo "Stop: sudo systemctl stop tradebot2-observe"
echo "Disable at reboot: sudo systemctl disable --now tradebot2-observe"
echo
sudo systemctl --no-pager --full status "$UNIT_NAME"
