#!/usr/bin/env bash
# Read-only BTC Delta India DEMO release blocker audit.
# No trade authorization, no local ledger writes, no service changes, no paid AI.
set -uo pipefail

usage() {
  printf 'Usage: bash ops/run_btc_demo_release_audit.sh <existing-btc-fire-id> [existing-data-directory]\n' >&2
  exit 2
}
[[ $# -ge 1 && $# -le 2 ]] || usage
FIRE_ID="$1"
[[ "$FIRE_ID" =~ ^[0-9a-fA-F]{32}$ ]] || usage

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)" || exit 2
DATA="${2:-$ROOT/data}"
if [[ ! -d "$DATA" || -L "$DATA" ]]; then
  printf 'BLOCKED: trusted_existing_data_directory_unavailable\n' >&2
  exit 2
fi
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  printf 'BLOCKED: virtualenv_python_unavailable\n' >&2
  exit 2
fi
if [[ -z "${DELTA_DEMO_API_KEY:-}" || -z "${DELTA_DEMO_API_SECRET:-}" ]]; then
  printf 'BLOCKED: demo_credentials_not_loaded_in_environment\n' >&2
  exit 2
fi
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
# These apply only to the diagnostic child processes, not running services.
export TRADEBOT_FIRE_DEMO_EXECUTION=false
export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false
export ENABLE_DEMO_ORDERS=false

BLOCKED=0
run_check() {
  local name="$1" rc=0
  shift
  printf '\n=== %s ===\n' "$name"
  "$@" || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    printf 'CHECK_STATUS: PASS (diagnostic only)\n'
  else
    printf 'CHECK_STATUS: BLOCKED (exit %s)\n' "$rc"
    BLOCKED=1
  fi
}
printf 'BTC DEMO RELEASE AUDIT — GET-only; no order authority\n'
printf 'Historical receipt: %s\n' "$FIRE_ID"
printf 'FIRE and Gold remain disabled; never use this report to unlock trading.\n'

run_check 'Broker leverage and isolated-margin compatibility' \
  "$PY" -m tradebot.fire_leverage_probe

run_check 'Existing equity receipt/checkpoint health' \
  "$PY" -c '
import json, sys
from tradebot.equity_checkpoint_health import checkpoint_health
try:
    result = checkpoint_health(sys.argv[1])
    safe = {name: result.get(name) for name in (
        "status", "daily_checkpoint", "weekly_checkpoint",
        "observation_status", "latest_receipt_status", "database_integrity",
        "checkpoint_prerequisites_met", "blocking_conditions", "alert_codes",
        "trade_authorized",
    )}
    print(json.dumps(safe, sort_keys=True))
    sys.exit(0 if result.get("status") == "healthy"
             and result.get("checkpoint_prerequisites_met") is True
             and result.get("trade_authorized") is False else 2)
except Exception:
    print(json.dumps({"status": "blocked", "reason": "equity_health_unavailable",
                      "trade_authorized": False}))
    sys.exit(2)
' "$DATA/fire-equity-risk.sqlite"

run_check 'Single-trade broker fill/wallet evidence (analysis only)' \
  "$PY" -m tradebot.fire_reconciliation_phase_probe --data-dir "$DATA"

run_check 'Combined host, equity, account-wide and bracket checks' \
  "$PY" -m tradebot.demo_release_evidence --data-dir "$DATA" --fire-id "$FIRE_ID"

run_check 'BTC historical extreme vs public mark/1m/spot context — manual review only' \
  "$PY" -m tradebot.candle_extreme_crosscheck --data-dir "$DATA"


printf '\n=== FINAL ===\n'
if [[ "$BLOCKED" -eq 0 ]]; then
  printf 'CHECK_STATUS: DIAGNOSTICS_CONSISTENT\n'
  printf 'Still required: independently verified market-data quality, durable financial reports, protection/rollback review and explicit supervised DEMO release approval.\n'
else
  printf 'CHECK_STATUS: RELEASE_BLOCKED — investigate each check above.\n'
fi
printf 'TRADING_ENABLED: false\n'
exit 2
