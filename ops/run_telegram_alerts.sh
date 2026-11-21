#!/usr/bin/env bash
# Free Telegram safety incident delivery; never connects to the broker.
set -euo pipefail
set +x
umask 077

PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
TOKEN_FILE="$HOME/.config/tradebot2/telegram.env"
if [[ ! -f "$TOKEN_FILE" || -L "$TOKEN_FILE" || ! -r "$TOKEN_FILE" ||
      "$(stat -c %a "$TOKEN_FILE")" != 600 ||
      ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "Refused: protected Telegram config (0600) or Python unavailable." >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$TOKEN_FILE"
set +a

# No Delta, GPT, trading or risk-write authority in this independent service.
unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET TB_API_KEY
unset PYTHONHOME PYTHONUSERBASE
export PYTHONPATH="$PROJECT/src"
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
export PYTHONUNBUFFERED=1

# Read-only, no network: refuse old packages or missing monitoring outbox.
"$PROJECT/.venv/bin/python" - "$PROJECT/src/tradebot/telegram_alerts.py" <<'PY'
import sys
from pathlib import Path
import tradebot.telegram_alerts as telegram
if Path(telegram.__file__).resolve() != Path(sys.argv[1]).resolve():
    raise SystemExit("REFUSED: Telegram relay source mismatch")
PY

"$PROJECT/.venv/bin/python" -m tradebot.telegram_alerts \
  --data-dir "$PROJECT/data" --check

exec "$PROJECT/.venv/bin/python" -m tradebot.telegram_alerts \
  --data-dir "$PROJECT/data"
