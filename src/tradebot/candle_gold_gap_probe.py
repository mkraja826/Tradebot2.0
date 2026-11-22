"""Bounded GET-only Delta India DEMO source check for missing Gold candles.

Reads the original candle archive through the existing read-only inventory.
Checks genuine public 5m and 1m source responses for missing timestamps.
Never writes, repairs, backfills, releases quarantine or authorizes trading.
Same-provider 1m agreement does not prove independent market accuracy.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json

from tradebot.candle_anomaly_inventory import inventory_archive, MAX_EXAMPLES
from tradebot.candle_source_diagnostic import _read, _aggregate
from tradebot.delta import DeltaDemo, DEMO_API

STEP = 300


def gold_gap_probe(exchange, data_dir, *, inventory_fn=inventory_archive, now=None):
    report = {
        "mode": "public_demo_gold_gap_source_probe",
        "status": "blocked",
        "reason": "not_started",
        "missing_gold_bars": None,
        "checked_bars": 0,
        "candidate_results": [],
        "archive_mutations": False,
        "financial_ledger_mutations": False,
        "broker_order_mutations": False,
        "credentialed_broker_calls": False,
        "ai_calls": 0,
        "same_provider_only": True,
        "independent_price_validation": False,
        "broker_archive_recovery_confirmed": False,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
    }
    if (getattr(exchange, "base_url", None) != DEMO_API
            or getattr(exchange, "allow_orders", None) is not False):
        report["reason"] = "public_read_only_demo_required"
        return report
    instant = now or datetime.now(timezone.utc)
    if (not isinstance(instant, datetime) or instant.tzinfo is None
            or instant.utcoffset() is None):
        report["reason"] = "trusted_utc_clock_required"
        return report
    instant = instant.astimezone(timezone.utc)
    month = instant.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous = (month.replace(day=1) -
                timedelta(days=1)).replace(day=1)
    earliest, latest = int(previous.timestamp()), int(month.timestamp())
    try:
        inv = inventory_fn(data_dir, now=instant)
        if inv.get("status") not in (
                "local_archive_issues_identified", "archive_windows_provisionally_complete"):
            report["reason"] = "original_archive_unverified"
            return report
        period = inv["periods"]["XAUTUSD_previous_month"]
        count = period["missing_bar_count"]
        times = period["missing_utc_examples"]
        truncated = period["examples_truncated"]["missing"]
        if (type(count) is not int or not 0 <= count <= MAX_EXAMPLES
                or truncated is not False or type(times) is not list
                or len(times) != count):
            report["reason"] = "missing_window_not_bounded"
            return report
        stamps = []
        for item in times:
            if type(item) is not str:
                raise ValueError("untrusted_timestamp")
            dt = datetime.fromisoformat(item)
            if (dt.tzinfo is None or dt.utcoffset() is None
                    or dt.utcoffset().total_seconds() != 0):
                raise ValueError("untrusted_timestamp")
            stamp = int(dt.timestamp())
            if not (earliest <= stamp < latest and stamp % STEP == 0):
                raise ValueError("untrusted_timestamp")
            stamps.append(stamp)
        if len(set(stamps)) != len(stamps):
            raise ValueError("duplicate_timestamp")
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError, OSError):
        report["reason"] = "original_gap_inventory_unverified"
        return report

    report["missing_gold_bars"] = count
    if count == 0:
        report["status"] = "no_missing_gold_bars_locally"
        report["reason"] = "local_inventory_only_not_independent_proof"
        return report
    complete = True
    for stamp in stamps:
        row = {
            "utc": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
            "trade_5m": "unavailable_or_invalid",
            "trade_1m": "unavailable_or_invalid",
            "same_provider_1m_5m_agreement": False,
        }
        five = minute = None
        try:
            five = _read(exchange, "XAUTUSD", "5m", stamp, STEP, 1)[0]
            row["trade_5m"] = "valid_public_broker_response"
        except Exception:
            pass  # Never expose provider exception bodies or raw responses.
        try:
            minute = _read(exchange, "XAUTUSD", "1m", stamp, 60, 5)
            row["trade_1m"] = "five_valid_public_minutes"
        except Exception:
            pass
        if five is not None and minute is not None:
            row["same_provider_1m_5m_agreement"] = five == _aggregate(minute)
        if not row["same_provider_1m_5m_agreement"]:
            complete = False
        report["checked_bars"] += 1
        report["candidate_results"].append(row)
    report["status"] = ("same_provider_candles_available_for_review"
                        if complete else "provider_gap_or_disagreement")
    report["reason"] = ("manual_archive_recovery_still_required"
                        if complete else "missing_or_inconsistent_public_evidence")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)
    report = gold_gap_probe(DeltaDemo(allow_orders=False), args.data_dir)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 2  # Probe can never grant trading authority or mark release green.


if __name__ == "__main__":
    raise SystemExit(main())
