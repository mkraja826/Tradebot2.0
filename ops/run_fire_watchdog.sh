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
# The environment may contain an inherited PYTHONPATH pointing to an old
# installed Tradebot package. Pin imports to this exact deployed checkout.
# Keep site-packages available for dependencies, but prevent user-site and
# inherited PYTHONHOME/PYTHONUSERBASE from changing import provenance.
unset PYTHONHOME PYTHONUSERBASE
export PYTHONNOUSERSITE=1
export PYTHONPATH="$PROJECT/src"
export PYTHONSAFEPATH=1

# No broker calls or database writes: refuse to start a daemon whose actual
# imported module/version differs from the deployed source we just verified.
"$PROJECT/.venv/bin/python" - "$PROJECT/src/tradebot/fire_watchdog.py" <<'PY'
import sys
from pathlib import Path
import tradebot.fire_watchdog as watchdog
expected = Path(sys.argv[1]).resolve()
if (Path(watchdog.__file__).resolve() != expected or
        getattr(watchdog, "WATCHDOG_RUNTIME_VERSION", None)
        != "watchdog-telemetry-v2-20261122"):
    raise SystemExit("REFUSED: watchdog source or runtime version mismatch")
PY

export ENABLE_DEMO_ORDERS=false
export PYTHONUNBUFFERED=1
exec "$PROJECT/.venv/bin/python" -m tradebot.fire_watchdog \
  --database "$PROJECT/data/fire-ops.sqlite" --interval 15
