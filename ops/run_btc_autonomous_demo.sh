#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /home/support/Tradebot2.0
set -a
source /home/support/.config/tradebot2/keys.env
set +a
export PYTHONPATH="$PWD/src"
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
exec .venv/bin/python -m tradebot.btc_autonomous_demo \
  --data-dir "$PWD/data" --serve
