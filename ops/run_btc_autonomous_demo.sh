#!/usr/bin/env bash
# Delta India DEMO: BTC isolated subaccount. Main ledger is never used here.
set -euo pipefail
set +x
umask 077
PROJECT=/home/support/Tradebot2.0
KEYDIR=/home/support/.config/tradebot2
ACCOUNT_DATA="$PROJECT/data/btc-isolated"
cd "$PROJECT"
[[ "$(id -un)" == support && -d "$ACCOUNT_DATA" && ! -L "$ACCOUNT_DATA" &&
    "$(stat -c %U "$ACCOUNT_DATA")" == support &&
    "$(stat -c %a "$ACCOUNT_DATA")" == 700 ]] ||
    { echo "Untrusted private isolated BTC data directory" >&2; exit 2; }
for secretfile in "$KEYDIR/keys.env" "$KEYDIR/btc-demo-keys.env"; do
    [[ -f "$secretfile" && ! -L "$secretfile" &&
        "$(stat -c %U "$secretfile")" == support &&
        "$(stat -c %a "$secretfile")" == 600 ]] ||
        { echo "Missing trusted DEMO credentials" >&2; exit 2; }
done
unset PYTHONHOME PYTHONUSERBASE
set -a
# Parent credentials are used for GET-only signed identity verification.
source "$KEYDIR/keys.env"
export TRADEBOT_PARENT_DEMO_API_KEY="$DELTA_DEMO_API_KEY"
export TRADEBOT_PARENT_DEMO_API_SECRET="$DELTA_DEMO_API_SECRET"
# Only the BTC child credentials may create a broker session for this worker.
source "$KEYDIR/btc-demo-keys.env"
set +a
export TRADEBOT_EXPECTED_DEMO_SUBACCOUNT=BTC
export PYTHONNOUSERSITE=1 PYTHONSAFEPATH=1 PYTHONPATH="$PROJECT/src"
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
exec .venv/bin/python -m tradebot.btc_autonomous_demo \
  --data-dir "$ACCOUNT_DATA" --serve
