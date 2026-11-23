#!/usr/bin/env bash
# GOLD XAUTUSD independent isolated DEMO account, DeepSeek-only decisions.
set -euo pipefail
set +x
umask 077
PROJECT=/home/support/Tradebot2.0
DIR="$PROJECT/data/gold-isolated"
CFG=/home/support/.config/tradebot2
cd "$PROJECT"
[[ "$(id -un)" == support && -d "$DIR" && ! -L "$DIR" &&
   "$(stat -c %U "$DIR")" == support && "$(stat -c %a "$DIR")" == 700 ]] ||
    { echo "Gold private ledger unavailable" >&2; exit 2; }
for secretfile in "$CFG/keys.env" "$CFG/gold-demo-keys.env"; do
    [[ -f "$secretfile" && ! -L "$secretfile" &&
       "$(stat -c %U "$secretfile")" == support &&
       "$(stat -c %a "$secretfile")" == 600 ]] ||
       { echo "Trusted DEMO account credentials unavailable" >&2; exit 2; }
done
unset PYTHONHOME PYTHONUSERBASE
set -a
source "$CFG/keys.env"
export TRADEBOT_PARENT_DEMO_API_KEY="$DELTA_DEMO_API_KEY"
export TRADEBOT_PARENT_DEMO_API_SECRET="$DELTA_DEMO_API_SECRET"
source "$CFG/gold-demo-keys.env"
set +a
export TRADEBOT_EXPECTED_DEMO_SUBACCOUNT=GOLD
export PYTHONNOUSERSITE=1 PYTHONSAFEPATH=1 PYTHONPATH="$PROJECT/src"
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
exec .venv/bin/python -m tradebot.gold_autonomous_demo --data-dir "$DIR" --serve
