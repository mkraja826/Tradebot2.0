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
# keys.env is sourced INSIDE this launcher, after systemd UnsetEnvironment.
# It could accidentally reintroduce TRADEBOT_FIRE_DEMO_EXECUTION=true.
# Allow DEMO entry mode only with the reviewed root-owned explicit opt-in
# drop-in, and never while the fail-closed disable marker is present.
FIRE_UNIT_DIR=/etc/systemd/system/tradebot2-dashboard.service.d
FIRE_OPT_IN="$FIRE_UNIT_DIR/fire-demo.conf"
FIRE_DISABLED="$FIRE_UNIT_DIR/99-fire-disabled.conf"
if [[ -e "$FIRE_DISABLED" || ! -f "$FIRE_OPT_IN" || -L "$FIRE_OPT_IN" ]] ||
   ! grep -Fxq 'Environment=TRADEBOT_FIRE_DEMO_EXECUTION=true' "$FIRE_OPT_IN"; then
  export TRADEBOT_FIRE_DEMO_EXECUTION=false
fi
# Never accept contract-count overrides inherited from keys.env.
export TRADEBOT_FIRE_MAX_CONTRACTS=1
export TRADEBOT_DASHBOARD_DATA="$PROJECT/data"
export PYTHONUNBUFFERED=1

exec "$PROJECT/.venv/bin/python" -m tradebot.dashboard --host 127.0.0.1 --port 8765
