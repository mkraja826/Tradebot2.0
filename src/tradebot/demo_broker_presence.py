"""Diagnostic-only Delta India DEMO account exposure observation.

This is intentionally separate from FIRE admission and the strict combined
release packet. It can observe authenticated broker exposure while an older
installation's *local* reconciliation ledger is absent. It NEVER treats
that absence as resolved, grants trading permission, repairs a database,
or changes the Gold one-shot lock. No order mutations or paid AI calls.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import os
import time

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.fire_broker_inventory import (
    _sample, SAMPLE_INTERVAL_SECONDS, MAX_SWEEP_SECONDS,
)

_SYMBOLS = frozenset(("BTCUSD", "XAUTUSD"))


def _valid_sample(s):
    """Only the fully checked shape produced by the existing GET-only sweeper."""
    if type(s) is not dict or set(s.get("realtime_fire_sizes", {})) != _SYMBOLS:
        return False
    ids = s.get("fire_product_ids")
    if (type(ids) is not dict or set(ids) != _SYMBOLS
            or any(type(v) is not int or v <= 0 for v in ids.values())
            or len(set(ids.values())) != 2):
        return False
    for name in ("account_margined_nonzero_positions", "account_open_orders"):
        if type(s.get(name)) is not int or s[name] < 0:
            return False
    if type(s.get("isolated_margin_observed")) is not bool:
        return False
    if type(s.get("margined_fire_consistency")) is not bool:
        return False
    for v in s["realtime_fire_sizes"].values():
        if type(v) not in (str, int, Decimal):
            return False
        try:
            d = Decimal(str(v))
        except (ValueError, InvalidOperation):
            return False
        if not d.is_finite() or d != d.to_integral_value():
            return False
    return True


def observe_demo_broker_presence(exchange, *, sampler=_sample,
                                 pause=time.sleep, monotonic=time.monotonic):
    """Two bounded authenticated sweeps; result is never release authority.

    Explicit injectable callbacks permit offline tests without broker access.
    The standard sampler uses authenticated GETs for unfiltered account margin
    positions, all pages of open orders, and BTC/Gold filtered positions.
    """
    report = {
        "environment": "delta-india-demo",
        "mode": "read_only_broker_only",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "ready_for_unattended_trading": False,
        "broker_order_mutations": False,
        "local_ledger_mutations": False,
        "ai_calls": 0,
        "local_reconciliation_complete": False,
        "historical_gold_order_verified": False,
        "historical_continuous_protection_proven": False,
        "independent_release_review_required": True,
        "status": "blocked_or_unverified",
        "samples_checked": 0,
        "sample_spacing_verified": False,
        "broker_positions_last": None,
        "broker_open_orders_last": None,
        "blockers": [],
    }
    blockers = report["blockers"]
    if (getattr(exchange, "base_url", None) != DEMO_API
            or getattr(exchange, "allow_orders", None) is not False):
        blockers.append("read_only_delta_demo_client_required")
        return report
    if not all(callable(f) for f in (sampler, pause, monotonic)):
        blockers.append("invalid_sampler_or_clock")
        return report

    samples = []
    for i in range(2):
        try:
            if i:
                pause(SAMPLE_INTERVAL_SECONDS)
                gap = monotonic() - previous_end
                if (type(gap) not in (int, float) or not math.isfinite(gap)
                        or gap < SAMPLE_INTERVAL_SECONDS):
                    blockers.append("sample_spacing_unverified")
                    break
                report["sample_spacing_verified"] = True
            start = monotonic()
            if type(start) not in (int, float) or not math.isfinite(start):
                blockers.append("invalid_observation_clock")
                break
            item = sampler(exchange)
            duration = monotonic() - start
            if (type(duration) not in (int, float) or not math.isfinite(duration)
                    or duration < 0 or duration > MAX_SWEEP_SECONDS):
                blockers.append("broker_sample_timing_unverified")
                break
            if not _valid_sample(item):
                blockers.append("broker_sample_schema_unverified")
                break
            samples.append(item)
            report["samples_checked"] += 1
            previous_end = monotonic()
        except Exception:
            # Never surface raw provider errors or credentials.
            blockers.append("authenticated_broker_read_unavailable")
            break

    if samples:
        last = samples[-1]
        report["broker_positions_last"] = last["account_margined_nonzero_positions"]
        report["broker_open_orders_last"] = last["account_open_orders"]
    if len(samples) != 2:
        blockers.append("two_complete_broker_samples_required")
    else:
        if samples[0] != samples[1]:
            blockers.append("broker_state_changed_between_samples")
        for item in samples:
            if not item["isolated_margin_observed"]:
                blockers.append("isolated_margin_unverified")
            if item["account_margined_nonzero_positions"]:
                blockers.append("account_position_exposure_present")
            if item["account_open_orders"]:
                blockers.append("account_open_orders_present")
            if not item["margined_fire_consistency"]:
                blockers.append("lagging_or_inconsistent_broker_positions")
            if any(Decimal(str(v)) != 0
                   for v in item["realtime_fire_sizes"].values()):
                blockers.append("btc_or_gold_position_exposure_present")
    report["blockers"] = sorted(set(blockers))
    if not report["blockers"]:
        report["status"] = "two_flat_broker_snapshots_only_not_release_authority"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    key = os.environ.get("DELTA_DEMO_API_KEY", "")
    secret = os.environ.get("DELTA_DEMO_API_SECRET", "")
    if not key or not secret:
        print(json.dumps({
            "environment": "delta-india-demo", "mode": "read_only_broker_only",
            "status": "blocked_or_unverified",
            "blockers": ["demo_credentials_unavailable"],
            "trade_authorized": False, "safe_to_enable_fire": False,
        }, sort_keys=True))
        return 2
    exchange = DeltaDemo(api_key=key, api_secret=secret, allow_orders=False)
    report = observe_demo_broker_presence(exchange)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == (
        "two_flat_broker_snapshots_only_not_release_authority") else 2


if __name__ == "__main__":
    raise SystemExit(main())
