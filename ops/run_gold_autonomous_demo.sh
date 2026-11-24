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
# Read-only signed account/market readiness without launching a trading loop.
case "${1:-}" in
  "") ;;
  --readiness) exec .venv/bin/python -m tradebot.gold_autonomous_readiness --data-dir "$DIR" ;;
  --provider-health)
    exec .venv/bin/python -c 'import json; from tradebot.ai import TopBillingClient,TOPBILLING_MODELS_URL,PlanError; from tradebot.gold_deepseek_probe import GOLD_MODEL;
try:
 r=TopBillingClient()._call(TOPBILLING_MODELS_URL,timeout=12); ok=isinstance(r.get("data"),list) and GOLD_MODEL in {m.get("id") for m in r["data"] if isinstance(m,dict)}; print(json.dumps({"provider":"topbilling","catalogue_reachable":True,"deepseek_route_available":ok,"paid_completion":False}))
except PlanError as e:
 print(json.dumps({"provider":"topbilling","catalogue_reachable":False,"error_category":str(e),"paid_completion":False}))' ;;

  *) echo "Unsupported Gold wrapper argument" >&2; exit 2 ;;
esac
exec .venv/bin/python -m tradebot.gold_autonomous_demo --data-dir "$DIR" --serve
