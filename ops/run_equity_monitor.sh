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

# Reject inherited Python module redirection from VM key/environment files.
# Use this checked-out collector, not any older installed tradebot package.
unset PYTHONHOME PYTHONUSERBASE TB_API_KEY
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1
export PYTHONPATH="$PROJECT/src"

# Source identity check only; does not fetch wallet or touch SQLite.
"$PROJECT/.venv/bin/python" - "$PROJECT/src/tradebot/equity_monitor.py" <<'PY'
import sys
from pathlib import Path
import tradebot.equity_monitor as monitor

if Path(monitor.__file__).resolve() != Path(sys.argv[1]).resolve():
    raise SystemExit("REFUSED: equity collector source path does not match deployed project")
PY

export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
export PYTHONUNBUFFERED=1
exec "$PROJECT/.venv/bin/python" -m tradebot.equity_monitor --data-dir "$PROJECT/data"
