#!/usr/bin/env bash
# Optional independent HTTPS alert bridge. No exchange client or order privilege.
# Configure a real off-machine receiver BEFORE running this as a service.
set -euo pipefail
set +x
umask 077

PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
ALERTS_FILE="$HOME/.config/tradebot2/alerts.env"
if [[ ! -f "$ALERTS_FILE" || ! -r "$ALERTS_FILE" ||
      -L "$ALERTS_FILE" || ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "Refused: private alert configuration or Python unavailable." >&2
  exit 2
fi
MODE="$(stat -c %a "$ALERTS_FILE")"
if [[ "$MODE" != "600" ]]; then
  echo "Refused: alert configuration must have mode 600." >&2
  exit 2
fi

# shellcheck disable=SC1090
set -a
source "$ALERTS_FILE"
set +a

# Unlike the dashboard, this service must not inherit any broker credentials
# or order-enable switches. Pin source to the exact production installation.
unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET TB_API_KEY
unset PYTHONHOME PYTHONUSERBASE
export PYTHONPATH="$PROJECT/src"
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
export PYTHONUNBUFFERED=1

# Read-only preflight; no web request or SQLite create operation.
"$PROJECT/.venv/bin/python" -m tradebot.offhost_alerts \
  --data-dir "$PROJECT/data" --check

exec "$PROJECT/.venv/bin/python" -m tradebot.offhost_alerts \
  --data-dir "$PROJECT/data"
