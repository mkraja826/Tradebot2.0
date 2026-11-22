"""Read-only BTC DEMO supervised-session risk foundation.

A fresh authenticated wallet observation can serve as a *candidate* short
session baseline without inventing a missed Monday opening. This module does
NOT integrate with /api/fire or grant any order permission. A separately
reviewed, durable one-attempt execution path must later recheck these limits
atomically, including current signed isolated-margin evidence and trusted BTC
historical data. Normal FIRE weekday/week checkpoint rules stay untouched.
"""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.equity_monitor import risk_health
from tradebot.equity_receipt import validate_receipt, EquityReadError
from tradebot.portfolio_equity_guard import amount, EquityRiskError, validated_watermark

MAX_SESSION_SECONDS = 900
MAX_SESSION_DECLINE = Decimal("0.005")
MAX_OBSERVED_PEAK_DRAWDOWN = Decimal("0.08")
MAX_UNEXPLAINED_EQUITY_INCREASE = Decimal("0.02")
ALLOWED_STANDARD_BLOCKERS = frozenset({"weekly_checkpoint_missed_window"})

def _utc_now():
    return datetime.now(timezone.utc)



def assess_supervised_session(baseline, current, observed_peak,
                              baseline_receipt, current_receipt, *, now):
    """Pure, bounded session budget for later one-attempt pilot integration.

    Evidence here is authenticated HTTPS transport, not a broker-issued
    cryptographic account signature. A session assessment alone never permits
    an order, even when its loss limits pass.
    """
    result = {
        "policy": "btc-demo-supervised-session-v1",
        "max_contracts": 1,
        "max_attempts": 1,
        "max_session_seconds": MAX_SESSION_SECONDS,
        "max_session_decline_fraction": str(MAX_SESSION_DECLINE),
        "max_observed_peak_drawdown_fraction": str(MAX_OBSERVED_PEAK_DRAWDOWN),
        "status": "blocked",
        "reason": "unverified_session_evidence",
        "session_elapsed_seconds": None,
        "within_session_limits": False,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
    }
    if (not isinstance(now, datetime) or now.tzinfo is None or
            now.utcoffset() is None):
        return result
    try:
        first = amount(baseline)
        last = amount(current)
        peak = amount(observed_peak)
        if not isinstance(baseline_receipt, dict):
            raise EquityReadError("equity_read_receipt_invalid")
        start_us = baseline_receipt.get("received_us")
        if type(start_us) is not int or start_us <= 0:
            raise EquityReadError("equity_read_receipt_invalid")
        start_clock = datetime.fromtimestamp(start_us / 1_000_000, timezone.utc)
        start = validate_receipt(first, baseline_receipt, now=start_clock)
        end = validate_receipt(last, current_receipt, now=now)
        elapsed = (end - start).total_seconds()
        if not 0 <= elapsed <= MAX_SESSION_SECONDS:
            result["reason"] = "session_not_within_fifteen_minutes"
            return result
        result["session_elapsed_seconds"] = int(elapsed)
        if peak < first:
            # Current authenticated equity can be higher than the *previous*
            # retained peak. It must not erase the historical peak itself.
            peak = first
        session_decline = max(Decimal(0), (first - last) / first)
        peak_decline = max(Decimal(0), (peak - last) / peak)
        unaccounted_gain = max(Decimal(0), (last - first) / first)
        if session_decline >= MAX_SESSION_DECLINE:
            result["reason"] = "supervised_session_loss_limit"
        elif peak_decline >= MAX_OBSERVED_PEAK_DRAWDOWN:
            result["reason"] = "historical_high_watermark_drawdown_limit"
        elif unaccounted_gain > MAX_UNEXPLAINED_EQUITY_INCREASE:
            result["reason"] = "possible_external_balance_change"
        else:
            result["status"] = "within_limits_review_only"
            result["reason"] = "requires_separate_broker_and_execution_release"
            result["within_session_limits"] = True
    except (ValueError, TypeError, OverflowError, EquityReadError, EquityRiskError):
        result["reason"] = "unverified_session_evidence"
    return result


def _identity(path):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("untrusted_equity_ledger")
    return metadata.st_dev, metadata.st_ino


def _read_original_high_watermark(path):
    identity = _identity(path)
    with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro",
                                 uri=True, timeout=3)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
            raise ValueError("original_equity_ledger_integrity_unverified")
        peak = validated_watermark(db)
        db.rollback()
    if _identity(path) != identity:
        raise ValueError("original_equity_ledger_replaced")
    return peak, identity


def inspect_btc_session_candidate(exchange, data_dir, *,
                                  now=None, health_fn=risk_health):
    """Propose a genuine fresh session equity baseline without any writes.

    Missed *weekly* opening is the only existing equity-health blocker
    tolerated for a nonauthorizing supervised-session proposal. Daily anchor,
    latest historical receipt, existing high watermark and operational
    watchdog/collector must all remain valid.
    """
    report = {
        "mode": "read_only_supervised_session_candidate",
        "environment": "delta-india-demo",
        "symbol": "BTCUSD",
        "status": "blocked",
        "reason": "not_checked",
        "standard_weekly_opening_missing": None,
        "daily_checkpoint_verified": False,
        "latest_receipt_verified": False,
        "watchdog_and_collector_healthy": False,
        "original_equity_history_integrity_verified": False,
        "fresh_session_wallet_baseline_verified": False,
        "session_budget_within_limits": False,
        "max_contracts": 1,
        "max_attempts": 1,
        "max_session_seconds": MAX_SESSION_SECONDS,
        "normal_fire_policy_unchanged": True,
        "original_equity_ledger_mutations": False,
        "new_session_ledger_mutations": False,
        "broker_order_mutations": False,
        "ai_calls": 0,
        "signed_account_margin_verified": False,
        "btc_historical_price_integrity_verified": False,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
    }
    if (getattr(exchange, "base_url", None) != DEMO_API or
            getattr(exchange, "allow_orders", None) is not False):
        report["reason"] = "readonly_delta_demo_client_required"
        return report
    instant = now if now is not None else _utc_now()
    if (not isinstance(instant, datetime) or instant.tzinfo is None or
            instant.utcoffset() is None):
        report["reason"] = "trusted_utc_clock_required"
        return report
    root = Path(data_dir)
    path = root / "fire-equity-risk.sqlite"
    if (not root.is_dir() or root.is_symlink() or
            not path.is_file() or path.is_symlink()):
        report["reason"] = "original_equity_ledger_unavailable"
        return report
    try:
        health = health_fn(path, at=instant)
        if type(health) is not dict:
            raise ValueError("untrusted_health_report")
        report["daily_checkpoint_verified"] = health.get("daily_checkpoint") == "verified"
        report["latest_receipt_verified"] = (
            health.get("latest_receipt_status") == "verified" and
            health.get("observation_status") == "fresh")
        monitor = health.get("monitoring")
        report["watchdog_and_collector_healthy"] = (
            type(monitor) is dict and monitor.get("alert_codes") == [] and
            all(monitor.get(k) == "healthy"
                for k in ("watchdog", "equity_collector")) and
            all(type(monitor.get(k)) in (int, float) and
                0 <= monitor[k] <= limit
                for k, limit in (("watchdog_age_seconds", 90),
                                 ("equity_collector_age_seconds", 180))))
        conditions = health.get("blocking_conditions")
        if (type(conditions) is not list or
                any(type(x) is not str for x in conditions)):
            raise ValueError("untrusted_equity_conditions")
        report["standard_weekly_opening_missing"] = (
            health.get("weekly_checkpoint") == "missed_window")
        if (health.get("database_integrity") != "verified" or
                not report["daily_checkpoint_verified"] or
                not report["latest_receipt_verified"] or
                not report["watchdog_and_collector_healthy"] or
                not set(conditions) <= ALLOWED_STANDARD_BLOCKERS):
            report["reason"] = "original_daily_receipts_or_monitoring_unverified"
            return report
        peak, identity = _read_original_high_watermark(path)
        report["original_equity_history_integrity_verified"] = True
        wallet = exchange.wallet_balances()
        if type(wallet) is not dict or type(wallet.get("meta")) is not dict:
            raise ValueError("signed_wallet_schema_unverified")
        equity = amount(wallet["meta"]["net_equity"])
        receipt = wallet.get("equity_read_receipt")
        # IMPORTANT: The initial health-check clock precedes a network GET.
        # A fresh response therefore may legitimately be newer than that
        # initial clock. Validate it against a fresh UTC clock read AFTER the
        # signed wallet response instead of rejecting the valid receipt as
        # a future clock jump.
        observed_at = instant if now is not None else _utc_now()
        age = (observed_at - instant).total_seconds()
        if not 0 <= age <= 30:
            report["reason"] = "wallet_probe_duration_or_clock_unverified"
            return report
        validate_receipt(equity, receipt, now=observed_at)
        if _identity(path) != identity:
            raise ValueError("original_equity_ledger_replaced")
        report["fresh_session_wallet_baseline_verified"] = True
        limits = assess_supervised_session(
            equity, equity, peak, receipt, receipt, now=observed_at)
        report["session_budget_within_limits"] = (
            limits["within_session_limits"] is True)
        if not report["session_budget_within_limits"]:
            report["reason"] = limits["reason"]
            return report
        report["status"] = "baseline_candidate_review_only"
        report["reason"] = "separate_one_shot_controller_and_broker_gates_required"
        return report
    except (KeyError, ValueError, TypeError, OverflowError, OSError,
            sqlite3.Error, EquityRiskError, EquityReadError):
        report["reason"] = "original_evidence_or_signed_wallet_unavailable"
        return report
    except Exception:
        # Never surface provider exception messages, IDs or balances.
        report["reason"] = "read_only_broker_request_unavailable"
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)
    client = DeltaDemo(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    result = inspect_btc_session_candidate(client, args.data_dir)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 2  # Never emit release success from a read-only pilot proposal.


if __name__ == "__main__":
    raise SystemExit(main())
