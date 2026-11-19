#!/usr/bin/env bash
# Independent 15-second bracket/flatness watcher for user-pressed FIRE trades.
# No GPT-6, DeepSeek or Kimi calls. No new entry orders.
set -euo pipefail
set +x
umask 077
PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
KEY_FILE="$HOME/.config/tradebot2/keys.env"
if [[ ! -r "$KEY_FILE" || ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "FIRE watchdog requires protected Delta Demo keys and Python." >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a
source "$KEY_FILE"
set +a
export ENABLE_DEMO_ORDERS=false
export PYTHONUNBUFFERED=1
exec "$PROJECT/.venv/bin/python" -m tradebot.fire_watchdog \
  --database "$PROJECT/data/fire-ops.sqlite" --interval 15
