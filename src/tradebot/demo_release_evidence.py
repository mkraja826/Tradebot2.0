"""Single-command, nonauthorizing read-only BTC DEMO release evidence.

This diagnostic intentionally cannot enable FIRE, submit/cancel orders, alter
leverage, repair ledgers, release the Gold lock, or approve a trial. It only
combines existing bounded read-only checks into a sanitized operator report.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.equity_checkpoint_health import checkpoint_health
from tradebot.fire_bracket_evidence import VALID_FIRE_ID, audit_bracket_fields
from tradebot.fire_broker_inventory import observe_broker_inventory
from tradebot.fire_commission_preflight import _fire_disabled, _services_active


def _clock_synchronized():
    """A missing/unavailable host NTP attestation is a release blocker."""
    result = subprocess.run(
        ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
        capture_output=True, text=True, check=False, timeout=3,
    )
    return result.returncode == 0 and result.stdout.strip() == "yes"


def observe_demo_release(
    exchange, data_dir, *, fire_id, clock_check=_clock_synchronized,
    service_check=_services_active, fire_disabled_check=_fire_disabled,
    health_check=checkpoint_health, inventory_check=observe_broker_inventory,
    bracket_check=audit_bracket_fields, pause=None,
):
    """Gather safe evidence; a clean result is still NEVER trade authority.

    All checks are injectable to run no-network, no-database fixture tests.
    In operation these callbacks are the built-in read-only implementations.
    """
    report = {
        "environment": "delta-india-demo", "symbol": "BTCUSD",
        "mode": "read_only", "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "trade_authorized": False, "safe_to_enable_fire": False,
        "ready_for_unattended_trading": False, "broker_order_mutations": False,
        "local_ledger_mutations": False, "ai_calls": 0,
        "independent_risk_review_required": True,
        "fresh_wallet_risk_assessment_completed": False,
        "broker_wide_fill_and_funding_reconciliation_complete": False,
        "historical_continuous_protection_proven": False,
        "status": "review_required",
        "checks": {
            "clock_synchronized": False, "services_active": False,
            "both_fire_endpoints_disabled": False,
            "equity_checkpoint_prerequisites_met": False,
            "two_flat_broker_samples_observed": False,
            "historical_order_fields_match": False,
        },
        "broker_summary": {
            "samples_checked": 0, "positions_last": None,
            "open_orders_last": None,
        },
        "blockers": [],
    }
    blockers = report["blockers"]
    # Reject invalid identity BEFORE calling any local or broker components.
    if getattr(exchange, "base_url", None) != DEMO_API or getattr(
            exchange, "allow_orders", None) is not False:
        blockers.append("read_only_delta_demo_client_required")
        return report
    if type(fire_id) is not str or VALID_FIRE_ID.fullmatch(fire_id) is None:
        blockers.append("invalid_completed_btc_fire_id")
        return report
    root = Path(data_dir)
    if not root.is_dir() or root.is_symlink():
        blockers.append("trusted_original_data_directory_required")
        return report

    # Do the cheap host and local checks first. If any fail, don't make
    # potentially unnecessary authenticated broker requests.
    checks = report["checks"]
    for name, code, check in (
        ("clock_synchronized", "system_clock_not_verified", clock_check),
        ("services_active", "required_monitor_services_unverified", service_check),
        ("both_fire_endpoints_disabled", "dashboard_fire_disabled_unverified",
         fire_disabled_check),
    ):
        try:
            checks[name] = check() is True
        except Exception:
            checks[name] = False
        if not checks[name]:
            blockers.append(code)
    try:
        health = health_check(root / "fire-equity-risk.sqlite")
        checks["equity_checkpoint_prerequisites_met"] = (
            type(health) is dict and health.get("status") == "healthy"
            and health.get("checkpoint_prerequisites_met") is True
            and health.get("trade_authorized") is False
            and health.get("blocking_conditions") == []
        )
    except Exception:
        pass
    if not checks["equity_checkpoint_prerequisites_met"]:
        blockers.append("signed_equity_checkpoint_health_unverified")
    if blockers:
        report["blockers"] = sorted(set(blockers))
        return report

    # Full-account + two-market GET-only broker observation. Always bounded,
    # with two timed sweeps and independent local SQLite evidence checks.
    try:
        options = {} if pause is None else {"pause": pause}
        inventory = inventory_check(exchange, root, **options)
        if type(inventory) is not dict:
            raise ValueError("Invalid broker inventory")
        report["broker_summary"] = {
            "samples_checked": inventory.get("samples_checked")
            if type(inventory.get("samples_checked")) is int else 0,
            "positions_last": inventory.get("broker_positions_last")
            if type(inventory.get("broker_positions_last")) is int else None,
            "open_orders_last": inventory.get("broker_open_orders_last")
            if type(inventory.get("broker_open_orders_last")) is int else None,
        }
        checks["two_flat_broker_samples_observed"] = (
            inventory.get("observation_status")
            == "two_flat_snapshots_observed_not_trade_authority"
            and inventory.get("samples_checked") == 2
            and inventory.get("sample_interval_verified") is True
            and inventory.get("broker_positions_last") == 0
            and inventory.get("broker_open_orders_last") == 0
            and inventory.get("order_mutations") is False
            and inventory.get("trade_authorized") is False
            and inventory.get("blockers") == []
        )
    except Exception:
        checks["two_flat_broker_samples_observed"] = False
    if not checks["two_flat_broker_samples_observed"]:
        blockers.append("account_wide_delta_demo_evidence_unverified")
        report["blockers"] = sorted(set(blockers))
        return report

    # A historic read is useful only after the current account-wide
    # observations passed. This comparison never proves temporal protection.
    try:
        historical = bracket_check(exchange, root, symbol="BTCUSD",
                                   fire_id=fire_id)
        checks["historical_order_fields_match"] = (
            type(historical) is dict
            and historical.get("observation_status")
            == "historical_order_fields_match_not_protection_proof"
            and historical.get("authenticated_order_gets") == 3
            and historical.get("local_evidence_stable_across_order_reads") is True
            and historical.get("blockers") == []
            and historical.get("trade_authorized") is False
            and historical.get("safe_to_enable_fire") is False
            and historical.get("is_historical_protection_proven") is False
            and historical.get("order_mutations") is False
        )
    except Exception:
        checks["historical_order_fields_match"] = False
    if not checks["historical_order_fields_match"]:
        blockers.append("historical_btc_bracket_fields_unverified")

    report["blockers"] = sorted(set(blockers))
    if not report["blockers"]:
        report["status"] = "limited_read_only_checks_consistent_not_execution_authority"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.getenv(
        "TRADEBOT_DASHBOARD_DATA", "data"))
    parser.add_argument("--fire-id", required=True,
                        help="Existing completed BTC FIRE UUID, 32 hex chars")
    args = parser.parse_args(argv)
    exchange = DeltaDemo(api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
                         api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
                         allow_orders=False)
    report = observe_demo_release(exchange, args.data_dir, fire_id=args.fire_id)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == (
        "limited_read_only_checks_consistent_not_execution_authority") else 2


if __name__ == "__main__":
    raise SystemExit(main())
