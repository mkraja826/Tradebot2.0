#!/usr/bin/env bash
# Dedicated NYSE cash-session-only DeepSeek read-only observer.
# Deliberately has NO parameter to enable order execution.
set -euo pipefail
set +x
umask 077

PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
KEY_FILE="$HOME/.config/tradebot2/keys.env"

if [[ ! -r "$KEY_FILE" ]]; then
  echo "Tradebot service: secure credentials file not found/readable. Stop." >&2
  exit 1
fi
if [[ ! -x "$PROJECT/.venv/bin/tradebot" ]]; then
  echo "Tradebot service: Python virtual environment missing. Stop." >&2
  exit 1
fi
if [[ ! -d "$PROJECT/data" ]]; then
  echo "Tradebot service: data directory missing. Stop." >&2
  exit 1
fi

# Export the existing one-time-imported secrets without printing their values.
# This file was created under ~/.config/tradebot2 and chmod 0600.
# shellcheck disable=SC1090
source "$KEY_FILE"
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_JOURNAL="$PROJECT/data/trades.jsonl"
export PYTHONUNBUFFERED=1

# 60 s polling; target one DeepSeek research attempt every hour ONLY
# between NYSE cash open and close (including early closes). No orders.
# Remain idle outside cash hours; FIRE and Kimi are separate processes.
exec "$PROJECT/.venv/bin/tradebot" run --mode observe \
  --schedule nyse \
  --nyse-cash-scan-only \
  --poll-seconds 60 \
  --ai-interval-seconds 3600 \
  --max-options 32
