#!/usr/bin/env bash
# Stage a candidate protective watchdog unit ONLY.
# Never install/enable/restart the active protective watchdog from this script.
set -euo pipefail
set +x
umask 077

if [[ "$(id -u)" -eq 0 ]]; then
  printf 'BLOCKED: use the normal VM user, not root\n' >&2
  exit 2
fi
PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
VM_USER="$(id -un)"
VM_GROUP="$(id -gn)"
VM_HOME="$HOME"

# Values are interpolated into a systemd candidate, not executed by this
# script. Reject characters that could change systemd directive boundaries.
for value in "$PROJECT" "$VM_HOME" "$VM_USER" "$VM_GROUP"; do
  if [[ ! "$value" =~ ^[A-Za-z0-9_./-]+$ ]]; then
    printf 'BLOCKED: unsafe candidate-unit identity or path\n' >&2
    exit 2
  fi
done

KEY_FILE="$VM_HOME/.config/tradebot2/keys.env"
DATA="$PROJECT/data"
if [[ ! -f "$KEY_FILE" || -L "$KEY_FILE" || ! -r "$KEY_FILE" ||
      "$(stat -c %a "$KEY_FILE")" != 600 ||
      ! -x "$PROJECT/.venv/bin/python" ||
      ! -f "$PROJECT/src/tradebot/fire_watchdog.py" ||
      ! -f "$PROJECT/ops/run_fire_watchdog.sh" ]]; then
  printf 'BLOCKED: original private DEMO keys and installed watchdog source required\n' >&2
  exit 2
fi
if [[ ! -d "$DATA" || -L "$DATA" ||
      ! -f "$DATA/fire-ops.sqlite" || -L "$DATA/fire-ops.sqlite" ||
      ! -f "$DATA/fire-xaut.sqlite" || -L "$DATA/fire-xaut.sqlite" ||
      ! -f "$DATA/fire-monitoring.sqlite" || -L "$DATA/fire-monitoring.sqlite" ]]; then
  printf 'BLOCKED: original existing FIRE/monitoring ledgers required\n' >&2
  exit 2
fi

STAGE_PARENT="$VM_HOME/.config/tradebot2"
STAGE="$STAGE_PARENT/staged-units"
if [[ -L "$VM_HOME/.config" || -L "$STAGE_PARENT" || -L "$STAGE" ]]; then
  printf 'BLOCKED: untrusted unit staging destination\n' >&2
  exit 2
fi
mkdir -p -- "$STAGE"
chmod 700 -- "$STAGE"
CANDIDATE="$(mktemp "$STAGE/tradebot2-fire-watchdog.service.XXXXXXXX")"
trap 'rm -f -- "$CANDIDATE"' ERR
cat > "$CANDIDATE" <<EOF
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
chmod 600 -- "$CANDIDATE"
trap - ERR

printf 'WATCHDOG_UNIT_CANDIDATE_STAGED: true\n'
printf 'CANDIDATE_FILE: %s\n' "$CANDIDATE"
printf 'SYSTEMD_UNIT_INSTALLED: false\n'
printf 'WATCHDOG_RESTARTED: false\n'
printf 'BROKER_STATE_CHANGED: false\n'
printf 'TRADING_ENABLED: false\n'
printf 'Operator signoff, two signed broker-flat sweeps, backups and a protected deployment window are required before a separate manual unit promotion.\n'
