"""Two-pass read-only broker gate for supervised Delta India DEMO staging.

This is evidence for an operator, not authorization to restart services, change
leverage, enable FIRE, or place orders. Margined positions can lag fills; both
samples must pass after an 11-second interval with entry permission disabled.
"""
import argparse
import json
import os
import time

from tradebot.delta import DeltaDemo
from tradebot.demo_upgrade_preflight import audit_demo_upgrade

LAG_SECONDS = 11


def verify_staging_samples(exchange, data_dir, *, pause=time.sleep):
    """Produce a sanitized report; never call AI, place an order or mutate DB."""
    report = {
        "environment": "delta-india-demo",
        "mode": "read_only",
        "order_mutations": False,
        "ai_calls": 0,
        "samples_checked": 0,
        "required_sample_interval_seconds": LAG_SECONDS,
        "account_margin_mode": None,
        "positions": None,
        "open_orders": None,
        "unresolved_fire_receipts": None,
        "leverage": {},
        "broker_flat_two_samples": False,
        "operator_may_stage_only_if_fire_disabled_and_watchdog_healthy": False,
        "safe_to_enable_fire": False,
        "blockers": [],
    }
    # Passing the positional data directory does not grant write permissions:
    # audit_demo_upgrade opens receipt SQLite in immutable read-only mode.
    samples = []
    for sample_index in range(2):
        if sample_index:
            try:
                pause(LAG_SECONDS)
            except Exception:
                report["blockers"].append("sample_interval_not_completed")
                break
        try:
            result = audit_demo_upgrade(exchange, data_dir)
            profile = exchange._request("GET", "/v2/profile", auth=True)["result"]
            if not isinstance(profile, dict) or profile.get("margin_mode") != "isolated":
                result["blockers"].append("account_isolated_margin_not_verified")
            else:
                report["account_margin_mode"] = "isolated"
        except Exception:
            report["blockers"].append("signed_preflight_unavailable")
            break
        report["samples_checked"] += 1
        samples.append(result)
        for blocker in result["blockers"]:
            if blocker not in report["blockers"]:
                report["blockers"].append(blocker)
        if not result["safe_to_stage_execution_restart"]:
            break

    if samples:
        latest = samples[-1]
        report["positions"] = latest["broker_positions"]
        report["open_orders"] = latest["broker_open_orders"]
        report["unresolved_fire_receipts"] = latest["unresolved_fire_receipts"]
        report["leverage"] = latest["leverage"]
    # Leverage >20x blocks new FIRE but does not block *read-only code staging*.
    report["broker_flat_two_samples"] = bool(
        len(samples) == 2 and
        all(item["safe_to_stage_execution_restart"] for item in samples) and
        not any(b.startswith("account_isolated_margin_not_verified")
                for b in report["blockers"]) and
        all(item["broker_positions"] == 0 and
            item["broker_open_orders"] == 0 and
            item["unresolved_fire_receipts"] == 0 and
            item["realtime_fire_positions"] == {"BTCUSD": 0, "XAUTUSD": 0}
            for item in samples)
    )
    report["operator_may_stage_only_if_fire_disabled_and_watchdog_healthy"] = (
        report["broker_flat_two_samples"]
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.getenv("TRADEBOT_DASHBOARD_DATA", "data"))
    arguments = parser.parse_args(argv)
    exchange = DeltaDemo(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    report = verify_staging_samples(exchange, arguments.data_dir)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["broker_flat_two_samples"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
