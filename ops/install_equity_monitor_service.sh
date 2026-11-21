#!/usr/bin/env bash
# Stages a NEW read-only service. Does not start/restart any service or enable FIRE.
set -euo pipefail
set +x
umask 077
if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as your normal VM SSH user, not root." >&2; exit 1
fi
PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
VM_USER="$(id -un)"
VM_GROUP="$(id -gn)"
VM_HOME="$HOME"
if [[ "$PROJECT" == *' '* || "$PROJECT" == *'%'* || "$VM_HOME" == *' '* || "$VM_HOME" == *'%'* ]]; then
  echo "Unsupported special characters in paths." >&2; exit 1
fi
if [[ ! -r "$VM_HOME/.config/tradebot2/keys.env" || ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "Protected credentials and installed virtualenv required." >&2; exit 1
fi
# Hard stop if invoked from an isolated review worktree or a different clone:
# the generated service always reads/writes $PROJECT/data. It must never
# accidentally create a second equity history outside the running system.
for service in tradebot2-dashboard.service tradebot2-fire-watchdog.service; do
  deployed_dir="$(systemctl show "$service" --property=WorkingDirectory --value --no-pager)"
  if [[ -z "$deployed_dir" || "$deployed_dir" != "$PROJECT" ]]; then
    echo "REFUSED: equity monitor source differs from deployed service working directory." >&2
    exit 1
  fi
done
if [[ -L "$PROJECT/data" || ! -d "$PROJECT/data" ||
      -L "$PROJECT/data/fire-equity-risk.sqlite" ||
      ! -f "$PROJECT/data/fire-equity-risk.sqlite" ]]; then
  echo "REFUSED: original existing risk ledger is unavailable or untrusted." >&2
  exit 1
fi
# A healthy SQLite file is not sufficient: on legacy VMs the receipt table
# and immutable triggers have not been migrated. Never stage a unit whose
# first collector cycle would create schema implicitly in the live data dir.
# This module opens the existing ledger in SQLite mode=ro and does not make
# broker requests, create checkpoints or grant trade authority.
if ! "$PROJECT/.venv/bin/python" -m tradebot.equity_install_preflight \
    --data-dir "$PROJECT/data"; then
  echo "REFUSED: independent equity ledger migration approval required." >&2
  exit 1
fi
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<EOF
[Unit]
Description=Tradebot 2.0 - read-only equity checkpoint and health monitor
After=network-online.target time-sync.target
Wants=network-online.target time-sync.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$VM_USER
Group=$VM_GROUP
Environment=HOME=$VM_HOME
WorkingDirectory=$PROJECT
ExecStart=/usr/bin/bash $PROJECT/ops/run_equity_monitor.sh
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
SyslogIdentifier=tradebot2-equity-monitor

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 0644 "$tmp" /etc/systemd/system/tradebot2-equity-monitor.service
sudo systemctl daemon-reload
echo "Unit staged only. Follow docs/EQUITY_CHECKPOINT_RECOVERY.md before operator activation."
