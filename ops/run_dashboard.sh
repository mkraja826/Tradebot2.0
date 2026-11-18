#!/usr/bin/env bash
# Browser UI: credential-backed signed GETs only, bound to VM loopback.
set -euo pipefail
set +x
umask 077
PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
KEY_FILE="$HOME/.config/tradebot2/keys.env"
if [[ ! -r "$KEY_FILE" ]]; then
  echo "Dashboard requires your protected VM credentials file; no keys printed." >&2
  exit 1
fi
if [[ ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "Dashboard requires project Python virtual environment." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$KEY_FILE"
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_DASHBOARD_DATA="$PROJECT/data"
export PYTHONUNBUFFERED=1

exec "$PROJECT/.venv/bin/python" -m tradebot.dashboard --host 127.0.0.1 --port 8765
