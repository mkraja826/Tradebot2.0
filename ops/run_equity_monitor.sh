#!/usr/bin/env bash
# Read-only Delta DEMO wallet collector; no entry or closeout permission.
set -euo pipefail
set +x
umask 077
PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
KEY_FILE="$HOME/.config/tradebot2/keys.env"
if [[ ! -r "$KEY_FILE" || ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "Equity monitor requires protected Delta DEMO credentials and Python." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$KEY_FILE"
set +a
unset TB_API_KEY
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
export PYTHONUNBUFFERED=1
exec "$PROJECT/.venv/bin/python" -m tradebot.equity_monitor --data-dir "$PROJECT/data"
