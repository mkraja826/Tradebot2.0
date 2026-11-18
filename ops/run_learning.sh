#!/usr/bin/env bash
# Dedicated optional Delta India DEMO trade-learning observer.
# Read-only signed GETs; Kimi paid calls require explicit service opt-in.
set -euo pipefail
set +x
umask 077

PROJECT="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
KEY_FILE="$HOME/.config/tradebot2/keys.env"
if [[ ! -r "$KEY_FILE" || ! -x "$PROJECT/.venv/bin/python" ]]; then
  echo "Learning watcher requires private VM keys and installed Python environment." >&2
  exit 1
fi
if [[ ! -d "$PROJECT/data" ]]; then
  echo "Learning watcher requires private data/ directory." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$KEY_FILE"
export ENABLE_DEMO_ORDERS=false
export PYTHONUNBUFFERED=1

if [[ "${TRADEBOT_KIMI_PAID_REVIEWS:-false}" == "true" ]]; then
  exec "$PROJECT/.venv/bin/python" -m tradebot.trade_learning_watch \
    --watch --interval 30 --database "$PROJECT/data/trade-learning.sqlite" --paid-kimi
fi
exec "$PROJECT/.venv/bin/python" -m tradebot.trade_learning_watch \
  --watch --interval 30 --database "$PROJECT/data/trade-learning.sqlite"
