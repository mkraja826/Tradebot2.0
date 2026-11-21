#!/usr/bin/env bash
# Stage ONLY the Healthchecks.io systemd oneshot and minute timer.
# Never auto-activate, never touch broker service units or account data.
set -euo pipefail
set +x
umask 077

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Refused: use the normal VM SSH user, not root." >&2
  exit 2
fi
PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
VM_HOME="$HOME"
VM_USER="$(id -un)"
VM_GROUP="$(id -gn)"
CONFIG="$HOME/.config/tradebot2/healthchecks.env"
NAME=tradebot2-healthchecks-ping

if [[ "$PROJECT" == *' '* || "$PROJECT" == *'%'* ||
      "$VM_HOME" == *' '* || "$VM_HOME" == *'%'* ]]; then
  echo "Refused: unsupported VM path." >&2
  exit 2
fi
if systemctl is-active --quiet "$NAME.timer"; then
  echo "Refused: Healthchecks timer already active; no implicit replacement." >&2
  exit 2
fi
for service in tradebot2-dashboard.service tradebot2-fire-watchdog.service tradebot2-equity-monitor.service tradebot2-telegram-alerts.service; do
  if ! systemctl is-active --quiet "$service"; then
    echo "Refused: required protective/notification service inactive." >&2
    exit 2
  fi
done
if [[ ! -f "$CONFIG" || -L "$CONFIG" || ! -r "$CONFIG" ||
      "$(stat -c %a "$CONFIG")" != 600 ||
      "$(stat -c %u "$CONFIG")" != "$(id -u)" ||
      ! -f "$PROJECT/src/tradebot/healthchecks_ping.py" ||
      ! -x "$PROJECT/.venv/bin/python" ||
      ! -f "$PROJECT/data/fire-monitoring.sqlite" ]]; then
  echo "Refused: original monitoring evidence or private URL config missing." >&2
  exit 2
fi
for unit in tradebot2-dashboard.service tradebot2-fire-watchdog.service tradebot2-equity-monitor.service; do
  installed="$(systemctl show "$unit" -p WorkingDirectory --value)"
  if [[ "$installed" != "$PROJECT" ]]; then
    echo "Refused: running protected service uses a different checkout." >&2
    exit 2
  fi
done

# No network and no database writes; do not display the token-bearing URL.
set -a
# shellcheck disable=SC1090
source "$CONFIG"
set +a
unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET TB_API_KEY
unset PYTHONHOME PYTHONUSERBASE
export PYTHONPATH="$PROJECT/src"
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1
export ENABLE_DEMO_ORDERS=false
"$PROJECT/.venv/bin/python" -m tradebot.healthchecks_ping \
  --data-dir "$PROJECT/data" --check

service_tmp="$(mktemp)"
timer_tmp="$(mktemp)"
trap 'rm -f "$service_tmp" "$timer_tmp"' EXIT

cat > "$service_tmp" <<EOF
[Unit]
Description=Tradebot 2.0 - independent free external heartbeat (no orders)
After=network-online.target tradebot2-fire-watchdog.service tradebot2-equity-monitor.service
Wants=network-online.target

[Service]
Type=oneshot
User=$VM_USER
Group=$VM_GROUP
Environment=HOME=$VM_HOME
WorkingDirectory=$PROJECT
ExecStart=/usr/bin/bash $PROJECT/ops/run_healthchecks_ping.sh
TimeoutStartSec=20
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
SyslogIdentifier=tradebot2-healthchecks-ping
EOF

cat > "$timer_tmp" <<EOF
[Unit]
Description=Tradebot 2.0 - ping external outage monitor every minute

[Timer]
OnActiveSec=20s
OnUnitInactiveSec=60s
AccuracySec=3s
RandomizedDelaySec=0
Unit=$NAME.service

[Install]
WantedBy=timers.target
EOF

sudo install -m 0644 "$service_tmp" "/etc/systemd/system/$NAME.service"
sudo install -m 0644 "$timer_tmp" "/etc/systemd/system/$NAME.timer"
sudo systemctl daemon-reload

echo "HEALTHCHECKS SERVICE AND TIMER STAGED ONLY"
echo "NOT STARTED OR ENABLED"
echo "NO TRADES, NO BROKER OR MONITOR SERVICE RESTARTS"
