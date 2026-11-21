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

# Source the protected environment first, then prevent a stale PYTHONPATH
# from selecting an old installed dashboard. Never start an unverified module.
unset PYTHONHOME PYTHONUSERBASE
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1
export PYTHONPATH="$PROJECT/src"

# Import-only, no service startup, no broker requests and no ledger writes.
"$PROJECT/.venv/bin/python" - "$PROJECT/src/tradebot/dashboard.py" <<'PY'
import sys
from pathlib import Path
import tradebot.dashboard as dashboard

if Path(dashboard.__file__).resolve() != Path(sys.argv[1]).resolve():
    raise SystemExit("REFUSED: dashboard source path does not match deployed project")
PY

export ENABLE_DEMO_ORDERS=false
export TRADEBOT_DASHBOARD_DATA="$PROJECT/data"
export PYTHONUNBUFFERED=1

exec "$PROJECT/.venv/bin/python" -m tradebot.dashboard --host 127.0.0.1 --port 8765
