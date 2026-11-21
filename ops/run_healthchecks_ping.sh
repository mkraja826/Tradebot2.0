#!/usr/bin/env bash
# One read-only monitor check plus one HTTPS ping; no Delta or trading access.
set -euo pipefail
set +x
umask 077

PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
CONFIG="$HOME/.config/tradebot2/healthchecks.env"

if [[ ! -f "$CONFIG" || -L "$CONFIG" || ! -r "$CONFIG" ||
      "$(stat -c %a "$CONFIG")" != 600 ||
      "$(stat -c %u "$CONFIG")" != "$(id -u)" ||
      ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "Refused: private Healthchecks config or interpreter unavailable." >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$CONFIG"
set +a

# Pin source AFTER loading private config, and never inherit trading power.
unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET TB_API_KEY
unset PYTHONHOME PYTHONUSERBASE
export PYTHONPATH="$PROJECT/src"
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1
export PYTHONDONTWRITEBYTECODE=1
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
export PYTHONUNBUFFERED=1

"$PROJECT/.venv/bin/python" - "$PROJECT/src/tradebot/healthchecks_ping.py" <<'PY'
import sys
from pathlib import Path
import tradebot.healthchecks_ping as healthchecks
if Path(healthchecks.__file__).resolve() != Path(sys.argv[1]).resolve():
    raise SystemExit("REFUSED: Healthchecks module source mismatch")
PY

# Includes strict local monitoring preflight; sends nothing on failure.
exec "$PROJECT/.venv/bin/python" -m tradebot.healthchecks_ping \
  --data-dir "$PROJECT/data" --ping
