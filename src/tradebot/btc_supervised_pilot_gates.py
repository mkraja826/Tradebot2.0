"""One-pass, GET-only BTC supervised DEMO pilot readiness (NOT order permission).

This combines the existing 15-minute session-baseline candidate, current
signed account-margin evidence, account-wide flatness and original six-period
BTC archive quality. It cannot create a FIRE permit, write DBs, call AI or
place an order. Current XAU exposure still blocks the BTC account-wide gate;
XAU missing historical candles are not treated as BTC model inputs.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sqlite3

from tradebot.btc_supervised_session import inspect_btc_session_candidate
from tradebot.candle_archive import CandleArchive
from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.fire_account_guard import require_flat_demo_account
from tradebot.signed_margin_mode import signed_account_margin_mode
from tradebot.operator_account_mode import read_manual_mode
from tradebot.btc_supervised_recent24h import inspect_recent_btc_window
from tradebot.market import _age_seconds, MarketDataError

REQUIRED_BTC_PERIODS = (
    "day", "previous_day", "week", "previous_week", "month", "previous_month",
)


class ReadOnlyArchive(CandleArchive):
    """Use existing levels logic without CandleArchive's write-capable init."""

    def __init__(self, path):
        p = Path(path)
        if not p.is_file() or p.is_symlink():
            raise ValueError("original_archive_unavailable")
        self.path = p.resolve()

    def connect(self):
        return sqlite3.connect(
            self.path.as_uri() + "?mode=ro", uri=True, timeout=5,
        )


def btc_required_period_quality(exchange, data_dir, *, now=None):
    """Original archive check only. Local completeness is NOT external proof."""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("utc_clock_unverified")
    ticker = exchange.ticker("BTCUSD")
    if (not isinstance(ticker, dict)
            or ticker.get("symbol") != "BTCUSD"
            or type(ticker.get("product_id")) is not int
            or ticker["product_id"] <= 0):
        raise ValueError("btc_product_unverified")
    try:
        mark = Decimal(str(ticker["mark_price"]))
        if not mark.is_finite() or mark <= 0:
            raise ValueError("btc_mark_unverified")
        # Delta ticker timestamps are delivered as numeric strings by some
        # API representations, and market.py already normalizes seconds,
        # milliseconds and microseconds. Preserve its clock-skew validation.
        age = _age_seconds(ticker.get("timestamp"), instant)
        if age > 30:
            raise ValueError("btc_quote_stale")
        path = Path(data_dir) / "delta-demo-candles.sqlite"
        levels = ReadOnlyArchive(path).levels(
            "BTCUSD", int(instant.timestamp()), float(mark))
        periods = levels["periods"]
        if type(periods) is not dict or set(periods) != set(REQUIRED_BTC_PERIODS):
            raise ValueError("btc_periods_incomplete")
        quality = {}
        for key in REQUIRED_BTC_PERIODS:
            value = periods[key]
            if type(value) is not dict:
                raise ValueError("btc_periods_invalid")
            status = value.get("quality_status")
            if status not in ("provisionally_valid", "incomplete",
                              "suspicious_extreme", "quarantined"):
                raise ValueError("btc_period_quality_unknown")
            quality[key] = status
        return quality
    except (ValueError, TypeError, OverflowError, KeyError,
            InvalidOperation, MarketDataError, sqlite3.Error, OSError):
        raise ValueError("btc_original_archive_or_quote_unverified") from None


def inspect_btc_pilot_gates(
    exchange, data_dir, *, now=None,
    session_fn=inspect_btc_session_candidate,
    margin_fn=signed_account_margin_mode,
    account_fn=require_flat_demo_account,
    quality_fn=btc_required_period_quality,
):
    report = {
        "mode": "read_only_btc_supervised_pilot_gates",
        "environment": "delta-india-demo",
        "symbol": "BTCUSD",
        "status": "blocked",
        "session_candidate_passed": False,
        "signed_isolated_margin_verified": False,
        "owner_declared_account_mode": "not_configured",
        "account_wide_flatness_verified": False,
        "btc_required_periods_provisionally_valid": False,
        "btc_recent24h_local_candidate_only": False,
        "btc_recent24h_source_verified_independently": False,
        "btc_period_quality": {},
        "independent_btc_trade_price_verification": False,
        "watchdog_protection_lifecycle_verified": False,
        "durable_one_attempt_controller_commissioned": False,
        "max_contracts_if_future_approved": 1,
        "blockers": [],
        "order_mutations": False,
        "ledger_mutations": False,
        "archive_mutations": False,
        "ai_calls": 0,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
    }
    if (getattr(exchange, "base_url", None) != DEMO_API or
            getattr(exchange, "allow_orders", None) is not False):
        report["blockers"] = ["readonly_delta_demo_client_required"]
        return report
    instant = now or datetime.now(timezone.utc)
    if (not isinstance(instant, datetime) or instant.tzinfo is None or
            instant.utcoffset() is None):
        report["blockers"] = ["trusted_clock_required"]
        return report

    try:
        # Never inject the pre-GET clock into live receipt validation.
        # Explicit `now` remains an injected offline-test evaluation time.
        session = session_fn(
            exchange, data_dir, **({"now": now} if now is not None else {})
        )
        report["session_candidate_passed"] = (
            type(session) is dict
            and session.get("status") == "baseline_candidate_review_only"
            and session.get("session_budget_within_limits") is True
            and session.get("trade_authorized") is False
            and session.get("safe_to_enable_fire") is False)
    except Exception:
        pass
    if not report["session_candidate_passed"]:
        report["blockers"].append("supervised_session_equity_unverified")

    # Owner declaration is informational; never replace signed margin proof.
    try:
        report["owner_declared_account_mode"] = read_manual_mode(exchange)["status"]
    except Exception:
        pass
    try:
        report["signed_isolated_margin_verified"] = (
            margin_fn(exchange) == "isolated")
    except Exception:
        pass
    if not report["signed_isolated_margin_verified"]:
        report["blockers"].append("account_signed_isolated_margin_unverified")
    else:
        # Account guard performs its own complete signed, current-account
        # margin and exposure checks. Do not accept filtered BTC-only flatness.
        try:
            proof = account_fn(exchange)
            report["account_wide_flatness_verified"] = (
                type(proof) is dict
                and proof.get("account_flat_verified") is True
                and proof.get("open_positions") == 0
                and proof.get("open_orders") == 0
                and set(proof.get("checked_markets", [])) == {"BTCUSD", "XAUTUSD"})
        except Exception:
            pass
        if not report["account_wide_flatness_verified"]:
            report["blockers"].append("account_wide_exposure_unverified")

    # Alternate 24h research input only, never a substitute for the six
    # period checks required by ordinary FIRE or signed trade-price proof.
    try:
        recent = inspect_recent_btc_window(data_dir, now=instant)
        report["btc_recent24h_local_candidate_only"] = (
            recent.get("status") == "recent24h_local_candidate_only"
            and recent.get("complete_contiguous_24h") is True
            and recent.get("independently_verified_btc_perpetual_prices") is False
            and recent.get("safe_to_enable_fire") is False)
    except Exception:
        pass
    try:
        quality = quality_fn(exchange, data_dir, now=instant)
        if type(quality) is dict and set(quality) == set(REQUIRED_BTC_PERIODS):
            if all(type(quality[k]) is str and quality[k] in
                   ("provisionally_valid", "incomplete",
                    "suspicious_extreme", "quarantined")
                   for k in REQUIRED_BTC_PERIODS):
                report["btc_period_quality"] = quality
                report["btc_required_periods_provisionally_valid"] = all(
                    quality[k] == "provisionally_valid"
                    for k in REQUIRED_BTC_PERIODS)
    except Exception:
        pass
    if not report["btc_required_periods_provisionally_valid"]:
        report["blockers"].append("btc_historical_integrity_unverified")

    if not report["blockers"]:
        report["status"] = "candidate_checks_passed_not_release_authority"
        # Independent perpetual trade-print proof, live SL/TP lifecycle
        # and a separate one-attempt execution controller still required.
    report["blockers"] = sorted(set(report["blockers"]))
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
    report = inspect_btc_pilot_gates(client, args.data_dir)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 2  # Diagnostic cannot authorize an order, even when checks pass.


if __name__ == "__main__":
    raise SystemExit(main())
