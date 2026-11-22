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
[[ "$FIRE_ID" =~ ^[0-9a-f]{32}$ ]] || usage

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)" || exit 2
DATA="${2:-$ROOT/data}"
if [[ ! -d "$DATA" || -L "$DATA" ]]; then
  printf 'BLOCKED: trusted_existing_data_directory_unavailable\n' >&2
  exit 2
fi
# The original VM may still be running a pre-merge release-audit checkout.
# Only inspect git; NEVER pull/checkout/restart services from a diagnostic.
MINIMUM_REVIEWED_BASE="c9f79d59696e440da73c4425a8efe30fbe08db0f"
if ! command -v git >/dev/null 2>&1; then
  printf 'BLOCKED: git_checkout_provenance_unavailable\n' >&2
  exit 2
fi
if [[ "$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null)" != "$ROOT" ]] ||
   ! git -C "$ROOT" merge-base --is-ancestor "$MINIMUM_REVIEWED_BASE" HEAD 2>/dev/null; then
  printf 'BLOCKED: reviewed_release_audit_source_not_deployed\n' >&2
  exit 2
fi
# Check tracked AND untracked executable sources, and never swallow a
# failed status command as an "empty/clean" result.
if ! SOURCE_STATUS="$(git -C "$ROOT" status --porcelain --untracked-files=all -- src/tradebot ops 2>/dev/null)"; then
  printf 'BLOCKED: source_integrity_cannot_be_checked\n' >&2
  exit 2
fi
if [[ -n "$SOURCE_STATUS" ]]; then
  printf 'BLOCKED: executable_release_audit_source_is_modified\n' >&2
  exit 2
fi
# An approved staged worktree intentionally has no virtualenv of its own.
# Only an explicitly selected interpreter may run reviewed staged source;
# it is NOT a source deployment and never changes the running service.
PY="${TRADEBOT_AUDIT_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PY" || ! -f "$ROOT/src/tradebot/fire_reconciliation_phase_probe.py" ]]; then
  printf 'BLOCKED: reviewed_source_or_explicit_interpreter_unavailable\n' >&2
  exit 2
fi
if [[ -n "${TRADEBOT_AUDIT_PYTHON:-}" ]] &&
   [[ "$PY" != /* || "$PY" == *
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
printf 'Historical receipt: selected existing local BTC FIRE (ID redacted)\n'
printf 'FIRE and Gold remain disabled; never use this report to unlock trading.\n'

run_check 'Signed DELTA DEMO identity GET from existing approved VM network' \
  "$PY" -m tradebot.delta_auth_diagnostic

run_check 'Independent signed full-account exposure even when margin remains unverified' \
  "$PY" -m tradebot.fire_exposure_only_probe

run_check 'Broker leverage and isolated-margin compatibility' \
  "$PY" -m tradebot.fire_leverage_probe

run_check 'Existing equity receipt/checkpoint health' \
  "$PY" -c '
import json, sys
from tradebot.equity_monitor import risk_health
try:
    result = risk_health(sys.argv[1])
    safe = {name: result.get(name) for name in (
        "status", "daily_checkpoint", "weekly_checkpoint",
        "observation_status", "latest_receipt_status", "database_integrity",
        "checkpoint_prerequisites_met", "blocking_conditions", "alert_codes",
        "trade_authorized",
    )}
    monitor = result.get("monitoring") if type(result.get("monitoring")) is dict else {}
    safe["monitoring"] = {
        "watchdog": monitor.get("watchdog"),
        "equity_collector": monitor.get("equity_collector"),
        "alert_codes": monitor.get("alert_codes"),
    }
    watched = all(
        monitor.get(name) == "healthy"
        and type(monitor.get(name + "_age_seconds")) in (int, float)
        and 0 <= monitor[name + "_age_seconds"] <= limit
        for name, limit in (("watchdog",90),("equity_collector",180))
    )
    print(json.dumps(safe, sort_keys=True))
    sys.exit(0 if result.get("status") == "healthy"
             and result.get("checkpoint_prerequisites_met") is True
             and result.get("blocking_conditions") == []
             and monitor.get("alert_codes") == []
             and watched
             and result.get("trade_authorized") is False else 2)
except Exception:
    print(json.dumps({"status": "blocked", "reason": "equity_health_unavailable",
                      "trade_authorized": False}))
    sys.exit(2)
' "$DATA/fire-equity-risk.sqlite"

run_check 'Actual BTC/Gold monthly archive gaps and suspicious UTC bar inventory' \
  "$PY" -m tradebot.candle_anomaly_inventory --data-dir "$DATA"

run_check 'Existing operator off-host webhook configuration and local monitor health (no network)' \
  "$PY" -m tradebot.offhost_alerts --data-dir "$DATA" --check

run_check 'Existing financial journal permissions (read only)' \
  "$PY" -c '
import json, os, stat, sys
from pathlib import Path
root = Path(sys.argv[1])
p = root / "trades.jsonl"
try:
    d = root.lstat()
    s = p.lstat()
    good = (stat.S_ISDIR(d.st_mode) and not (d.st_mode & 0o077)
            and stat.S_ISREG(s.st_mode) and s.st_nlink == 1
            and not (s.st_mode & 0o077))
    print(json.dumps({"status": "private" if good else "unsafe_permissions",
                      "journal_present": True, "file_mode": oct(s.st_mode & 0o777),
                      "trade_authorized": False, "file_mutations": False}))
    sys.exit(0 if good else 2)
except Exception:
    print(json.dumps({"status": "journal_source_unavailable",
                      "trade_authorized": False, "file_mutations": False}))
    sys.exit(2)
' "$DATA"

run_check 'Single-trade broker fill/wallet evidence (analysis only)' \
  "$PY" -m tradebot.fire_reconciliation_phase_probe --data-dir "$DATA" --fire-id "$FIRE_ID"

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
\n'* || "$PY" == *
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
printf 'Historical receipt: selected existing local BTC FIRE (ID redacted)\n'
printf 'FIRE and Gold remain disabled; never use this report to unlock trading.\n'

run_check 'Signed DELTA DEMO identity GET from existing approved VM network' \
  "$PY" -m tradebot.delta_auth_diagnostic

run_check 'Broker leverage and isolated-margin compatibility' \
  "$PY" -m tradebot.fire_leverage_probe

run_check 'Existing equity receipt/checkpoint health' \
  "$PY" -c '
import json, sys
from tradebot.equity_monitor import risk_health
try:
    result = risk_health(sys.argv[1])
    safe = {name: result.get(name) for name in (
        "status", "daily_checkpoint", "weekly_checkpoint",
        "observation_status", "latest_receipt_status", "database_integrity",
        "checkpoint_prerequisites_met", "blocking_conditions", "alert_codes",
        "trade_authorized",
    )}
    monitor = result.get("monitoring") if type(result.get("monitoring")) is dict else {}
    safe["monitoring"] = {
        "watchdog": monitor.get("watchdog"),
        "equity_collector": monitor.get("equity_collector"),
        "alert_codes": monitor.get("alert_codes"),
    }
    watched = all(
        monitor.get(name) == "healthy"
        and type(monitor.get(name + "_age_seconds")) in (int, float)
        and 0 <= monitor[name + "_age_seconds"] <= limit
        for name, limit in (("watchdog",90),("equity_collector",180))
    )
    print(json.dumps(safe, sort_keys=True))
    sys.exit(0 if result.get("status") == "healthy"
             and result.get("checkpoint_prerequisites_met") is True
             and result.get("blocking_conditions") == []
             and monitor.get("alert_codes") == []
             and watched
             and result.get("trade_authorized") is False else 2)
except Exception:
    print(json.dumps({"status": "blocked", "reason": "equity_health_unavailable",
                      "trade_authorized": False}))
    sys.exit(2)
' "$DATA/fire-equity-risk.sqlite"

run_check 'Actual BTC/Gold monthly archive gaps and suspicious UTC bar inventory' \
  "$PY" -m tradebot.candle_anomaly_inventory --data-dir "$DATA"

run_check 'Single-trade broker fill/wallet evidence (analysis only)' \
  "$PY" -m tradebot.fire_reconciliation_phase_probe --data-dir "$DATA" --fire-id "$FIRE_ID"

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
\r'* ]]; then
  printf 'BLOCKED: invalid_external_python_path\n' >&2
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
printf 'Historical receipt: selected existing local BTC FIRE (ID redacted)\n'
printf 'FIRE and Gold remain disabled; never use this report to unlock trading.\n'

run_check 'Signed DELTA DEMO identity GET from existing approved VM network' \
  "$PY" -m tradebot.delta_auth_diagnostic

run_check 'Broker leverage and isolated-margin compatibility' \
  "$PY" -m tradebot.fire_leverage_probe

run_check 'Existing equity receipt/checkpoint health' \
  "$PY" -c '
import json, sys
from tradebot.equity_monitor import risk_health
try:
    result = risk_health(sys.argv[1])
    safe = {name: result.get(name) for name in (
        "status", "daily_checkpoint", "weekly_checkpoint",
        "observation_status", "latest_receipt_status", "database_integrity",
        "checkpoint_prerequisites_met", "blocking_conditions", "alert_codes",
        "trade_authorized",
    )}
    monitor = result.get("monitoring") if type(result.get("monitoring")) is dict else {}
    safe["monitoring"] = {
        "watchdog": monitor.get("watchdog"),
        "equity_collector": monitor.get("equity_collector"),
        "alert_codes": monitor.get("alert_codes"),
    }
    watched = all(
        monitor.get(name) == "healthy"
        and type(monitor.get(name + "_age_seconds")) in (int, float)
        and 0 <= monitor[name + "_age_seconds"] <= limit
        for name, limit in (("watchdog",90),("equity_collector",180))
    )
    print(json.dumps(safe, sort_keys=True))
    sys.exit(0 if result.get("status") == "healthy"
             and result.get("checkpoint_prerequisites_met") is True
             and result.get("blocking_conditions") == []
             and monitor.get("alert_codes") == []
             and watched
             and result.get("trade_authorized") is False else 2)
except Exception:
    print(json.dumps({"status": "blocked", "reason": "equity_health_unavailable",
                      "trade_authorized": False}))
    sys.exit(2)
' "$DATA/fire-equity-risk.sqlite"

run_check 'Actual BTC/Gold monthly archive gaps and suspicious UTC bar inventory' \
  "$PY" -m tradebot.candle_anomaly_inventory --data-dir "$DATA"

run_check 'Single-trade broker fill/wallet evidence (analysis only)' \
  "$PY" -m tradebot.fire_reconciliation_phase_probe --data-dir "$DATA" --fire-id "$FIRE_ID"

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
