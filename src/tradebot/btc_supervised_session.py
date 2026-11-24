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
from tradebot.equity_monitor import (
    risk_health, demo_monitoring_operational, DAILY_ONLY_WARNING,
    PORTFOLIO_LOSS_WARNING,
)
from tradebot.equity_receipt import validate_receipt, EquityReadError
from tradebot.equity_policy_core import amount, EquityRiskError, validated_watermark

MAX_SESSION_SECONDS = 900
MAX_SESSION_DECLINE = Decimal("0.005")
MAX_OBSERVED_PEAK_DRAWDOWN = Decimal("0.08")
MAX_UNEXPLAINED_EQUITY_INCREASE = Decimal("0.02")
ALLOWED_STANDARD_BLOCKERS = frozenset({"weekly_checkpoint_missed_window"})
LOSS_THRESHOLD_REASONS = frozenset({
    "supervised_session_loss_limit",
    "historical_high_watermark_drawdown_limit",
})

def _utc_now():
    return datetime.now(timezone.utc)



def assess_supervised_session(baseline, current, observed_peak,
                              baseline_receipt, current_receipt, *, now,
                              allow_loss_warnings=False):
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
        "quality_warnings": [],
        "loss_threshold_mode": (
            "warnings_only" if allow_loss_warnings else "enforced"),
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
        # Only deterministic financial loss thresholds are optional for
        # BTC autonomous DEMO research. External balance changes, stale
        # receipts, session expiry and integrity faults remain hard failures.
        if allow_loss_warnings and result["reason"] in LOSS_THRESHOLD_REASONS:
            result["quality_warnings"] = [result["reason"]]
            result["status"] = "equity_loss_warning_review_only"
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



def isolated_btc_signed_genesis_window(path, health, instant, *, account="BTC"):
    """Truthful first UTC day exception for a newly provisioned DEMO ledger.

    There was no opening snapshot before the child account began collecting
    equity. Verify immutable first-day equity and authentic transport receipts
    rather than relabelling a missed 00:00-00:05 UTC opening as verified.
    The exception expires at the next midnight; normal daily requirements
    apply automatically from then onward. Never applies to main/Gold FIRE.
    """
    if (account not in ("BTC", "GOLD")
            or os.environ.get("TRADEBOT_EXPECTED_DEMO_SUBACCOUNT") != account
            or path.parent.name != account.lower() + "-isolated"
            or path.is_symlink()
            or path.parent.is_symlink() or path.parent.parent.is_symlink()
            or type(health) is not dict
            or health.get("daily_checkpoint") != "missed_window"
            or health.get("weekly_checkpoint") != "missed_window"
            or health.get("database_integrity") != "verified"
            or health.get("latest_receipt_status") != "verified"
            or health.get("observation_status") != "fresh"
            or not isinstance(instant, datetime) or instant.tzinfo is None):
        return False
    expected_conditions = {
        "daily_checkpoint_missed_window", "weekly_checkpoint_missed_window"}
    conditions = health.get("blocking_conditions")
    if (type(conditions) is not list
            or any(type(code) is not str for code in conditions)
            or not expected_conditions.issubset(set(conditions))
            or not set(conditions) <= (expected_conditions | {
                DAILY_ONLY_WARNING, PORTFOLIO_LOSS_WARNING})):
        return False
    utc_day = instant.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    anchor_end = int(utc_day.timestamp() * 1_000_000) + 300_000_000
    day_end = int((utc_day.timestamp() + 86400) * 1_000_000)
    try:
        identity = _identity(path)
        with closing(sqlite3.connect(
                path.absolute().as_uri() + "?mode=ro",
                uri=True, timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                return False
            first = db.execute(
                "SELECT observed_us,equity_usd,origin FROM equity_evidence "
                "ORDER BY observed_us ASC LIMIT 1").fetchone()
            if (first is None or type(first[0]) is not int
                    or not anchor_end <= first[0] < day_end
                    or first[0] > int(instant.timestamp() * 1_000_000)
                    or first[2] != "delta_demo_signed_wallet"):
                return False
            saved = db.execute(
                "SELECT receipt FROM equity_read_receipts "
                "WHERE observed_us=?", (first[0],)).fetchone()
            if saved is None:
                return False
            receipt = json.loads(saved[0])
            if (type(receipt) is not dict
                    or receipt.get("received_us") != first[0]):
                return False
            first_at = datetime.fromtimestamp(
                first[0] / 1_000_000, timezone.utc)
            if int(validate_receipt(first[1], receipt, now=first_at).timestamp()
                   * 1_000_000) != first[0]:
                return False
            validated_watermark(db)
            db.rollback()
        return _identity(path) == identity
    except (OSError, sqlite3.Error, ValueError, TypeError,
            OverflowError, EquityRiskError, EquityReadError, KeyError):
        return False


def inspect_btc_session_candidate(exchange, data_dir, *,
                                  now=None, health_fn=risk_health,
                                  allow_daily_loss_warning=False,
                                  allow_portfolio_loss_warnings=False,
                                  allow_initial_isolated_genesis=False,
                                  isolated_genesis_account="BTC",
                                  expected_market_symbol="BTCUSD"):
    """Propose a genuine fresh session equity baseline without any writes.

    A missed weekly opening is tolerated. Only opted-in autonomous DEMO
    checks may also treat a typed daily-only collector breach as a warning.
    Daily anchor,
    latest historical receipt, existing high watermark and operational
    watchdog/collector must all remain valid.
    """
    report = {
        "mode": "read_only_supervised_session_candidate",
        "environment": "delta-india-demo",
        "symbol": expected_market_symbol,
        "status": "blocked",
        "reason": "not_checked",
        "standard_weekly_opening_missing": None,
        "daily_checkpoint_verified": False,
        "provisional_first_day_signed_genesis": False,
        "latest_receipt_verified": False,
        "watchdog_and_collector_healthy": False,
        "original_equity_history_integrity_verified": False,
        "fresh_session_wallet_baseline_verified": False,
        "session_budget_within_limits": False,
        "quality_warnings": [],
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
        report["watchdog_and_collector_healthy"] = demo_monitoring_operational(
            monitor, allow_daily_loss_warning=allow_daily_loss_warning,
            allow_portfolio_loss_warnings=allow_portfolio_loss_warnings)
        conditions = health.get("blocking_conditions")
        if (type(conditions) is not list or
                any(type(x) is not str for x in conditions)):
            raise ValueError("untrusted_equity_conditions")
        report["standard_weekly_opening_missing"] = (
            health.get("weekly_checkpoint") == "missed_window")
        provisional = (allow_initial_isolated_genesis
            and isolated_btc_signed_genesis_window(
                path, health, instant, account=isolated_genesis_account))
        report["provisional_first_day_signed_genesis"] = bool(provisional)
        if (health.get("database_integrity") != "verified" or
                not (report["daily_checkpoint_verified"] or provisional) or
                not report["latest_receipt_verified"] or
                not report["watchdog_and_collector_healthy"] or
                not set(conditions) <= (ALLOWED_STANDARD_BLOCKERS |
                    ({"daily_checkpoint_missed_window"} if provisional else set()) |
                    ({DAILY_ONLY_WARNING} if allow_daily_loss_warning else set()) |
                    ({PORTFOLIO_LOSS_WARNING} if allow_portfolio_loss_warnings
                     else set()))):
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
            equity, equity, peak, receipt, receipt, now=observed_at,
            allow_loss_warnings=allow_portfolio_loss_warnings)
        report["quality_warnings"] = sorted(set(limits["quality_warnings"]) |
            (set(conditions) & {
                DAILY_ONLY_WARNING, PORTFOLIO_LOSS_WARNING}) |
            ({"provisional_first_day_signed_genesis"} if provisional else set()))
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
