#!/usr/bin/env bash
# Per-account Delta India DEMO watchdog/equity collector. NEVER places entries.
# Usage: run_isolated_demo_monitor.sh BTC|GOLD watchdog|equity
set -euo pipefail
set +x
umask 077
if [[ ${#} != 2 ]]; then echo "Expected account and role" >&2; exit 2; fi
ACCOUNT="$1"
ROLE="$2"
PROJECT="/home/support/Tradebot2.0"
ROOT="/home/support/.config/tradebot2"
case "$ACCOUNT:$ROLE" in
  BTC:watchdog|BTC:equity)
    SUB="$ROOT/btc-demo-keys.env"
    DATA="$PROJECT/data/btc-isolated"
    SYMBOL=BTCUSD
    ;;
  GOLD:watchdog|GOLD:equity)
    SUB="$ROOT/gold-demo-keys.env"
    DATA="$PROJECT/data/gold-isolated"
    SYMBOL=XAUTUSD
    ;;
  *) echo "Invalid isolated demo account/role" >&2; exit 2 ;;
esac
# An isolated account MUST NOT use the legacy main FIRE/equity ledgers.
[[ "$(id -un)" == support && ! -L "$DATA" && -d "$DATA" &&
    "$(stat -c %a "$DATA")" == 700 && "$(stat -c %U "$DATA")" == support ]] ||
    { echo "Untrusted isolated demo data directory" >&2; exit 2; }
for f in "$ROOT/keys.env" "$SUB"; do
    [[ -f "$f" && ! -L "$f" && "$(stat -c %U "$f")" == support &&
        "$(stat -c %a "$f")" == 600 ]] ||
        { echo "Isolated account credentials unavailable" >&2; exit 2; }
done
[[ -x "$PROJECT/.venv/bin/python" ]] ||
    { echo "No pinned python interpreter" >&2; exit 2; }
unset PYTHONHOME PYTHONUSERBASE
export PYTHONNOUSERSITE=1 PYTHONSAFEPATH=1 PYTHONPATH="$PROJECT/src"
set -a
# Parent credentials are used ONLY for signed GET identity attestation.
# The only trade-capable credentials in DELTA_DEMO_API_* come from the child.
source "$ROOT/keys.env"
export TRADEBOT_PARENT_DEMO_API_KEY="$DELTA_DEMO_API_KEY"
export TRADEBOT_PARENT_DEMO_API_SECRET="$DELTA_DEMO_API_SECRET"
source "$SUB"
set +a
export TRADEBOT_EXPECTED_DEMO_SUBACCOUNT="$ACCOUNT"
export ENABLE_DEMO_ORDERS=false
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
# Verify the exact code provenance and exact signed child/parent relationship
# before starting a long-lived monitor. An owner declaration is never proof.
"$PROJECT/.venv/bin/python" - "$PROJECT/src/tradebot/signed_margin_mode.py" <<'PY'
import os, sys
from pathlib import Path
from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.signed_margin_mode import signed_account_margin_mode
import tradebot.signed_margin_mode as source
if Path(source.__file__).resolve() != Path(sys.argv[1]).resolve():
    raise SystemExit("Refusing unpinned margin attestation module")
b = DeltaDemo(api_key=os.environ["DELTA_DEMO_API_KEY"],
              api_secret=os.environ["DELTA_DEMO_API_SECRET"],
              allow_orders=False)
if b.base_url != DEMO_API or signed_account_margin_mode(b) != "isolated":
    raise SystemExit("Signed isolated subaccount identity unavailable")
PY
cd "$PROJECT"
if [[ "$ROLE" == watchdog ]]; then
    # A watchdog may only manage positions represented by THIS ledger.
    # Scope Gold and BTC independently; default manual watchdog is unchanged.
    if [[ "$ACCOUNT" == BTC ]]; then
        LEDGER="$DATA/fire-ops.sqlite"
    else
        LEDGER="$DATA/fire-xaut.sqlite"
    fi
    exec "$PROJECT/.venv/bin/python" -m tradebot.fire_watchdog \
        --database "$LEDGER" --interval 15 --symbol "$SYMBOL"
fi
# Wallet collector has no order authority and writes to account-local DB only.
exec "$PROJECT/.venv/bin/python" -m tradebot.equity_monitor \
    --data-dir "$DATA"
