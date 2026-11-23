#!/usr/bin/env bash
# Read-only isolated BTC or Gold Delta DEMO Telegram incident delivery.
set -euo pipefail
set +x
umask 077
[[ $# -ge 1 && $# -le 2 ]] || { echo "Expected BTC or GOLD" >&2; exit 2; }
ACCOUNT="$1"
ACTION="${2:-}"
case "$ACCOUNT" in
  BTC) NAME=btc-isolated ;;
  GOLD) NAME=gold-isolated ;;
  *) echo "Unknown isolated subaccount" >&2; exit 2 ;;
esac
case "$ACTION" in
  ""|--baseline|--test|--once|--check) ;;
  *) echo "Unsupported relay action" >&2; exit 2 ;;
esac
PROJECT=/home/support/Tradebot2.0
DATA="$PROJECT/data/$NAME"
TOKEN_FILE="$HOME/.config/tradebot2/telegram.env"
[[ "$(id -un)" == support && -d "$DATA" && ! -L "$DATA" &&
    "$(stat -c %a "$DATA")" == 700 &&
    "$(stat -c %U "$DATA")" == support &&
    -f "$TOKEN_FILE" && ! -L "$TOKEN_FILE" &&
    "$(stat -c %a "$TOKEN_FILE")" == 600 &&
    "$(stat -c %U "$TOKEN_FILE")" == support &&
    -x "$PROJECT/.venv/bin/python" ]] ||
    { echo "Trusted isolated DEMO monitoring configuration unavailable" >&2; exit 2; }
set -a
source "$TOKEN_FILE"
set +a
unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET TB_API_KEY
unset PYTHONHOME PYTHONUSERBASE
export PYTHONPATH="$PROJECT/src" PYTHONNOUSERSITE=1 PYTHONSAFEPATH=1
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
export TRADEBOT_ALERT_ACCOUNT="$ACCOUNT"
export PYTHONUNBUFFERED=1
cd "$PROJECT"
"$PROJECT/.venv/bin/python" - "$PROJECT/src/tradebot/telegram_alerts.py" <<'PY'
import sys
from pathlib import Path
import tradebot.telegram_alerts as relay
if Path(relay.__file__).resolve() != Path(sys.argv[1]).resolve():
    raise SystemExit("Invalid Telegram relay source")
PY
# Read-only local outbox integrity check; does not send any network traffic.
"$PROJECT/.venv/bin/python" -m tradebot.telegram_alerts --data-dir "$DATA" --check
if [[ -n "$ACTION" ]]; then
    exec "$PROJECT/.venv/bin/python" -m tradebot.telegram_alerts \
        --data-dir "$DATA" "$ACTION"
fi
exec "$PROJECT/.venv/bin/python" -m tradebot.telegram_alerts --data-dir "$DATA"
