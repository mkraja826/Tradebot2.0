"""One approved GPT-6 BTCUSD DEMO FIRE attempt; dashboard remains disabled.

Default command is read-only. Execute requires an interactive operator, exact
typed consent, fresh broker and session checks and a durable one-use marker.
The underlying FIRE controller rechecks equity, account-wide flatness, margin,
model risk and broker brackets. No retry after ambiguity or model WAIT.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from tradebot.btc_supervised_execution import SupervisedBTCController
from tradebot.btc_supervised_recent24h import inspect_recent_btc_window
from tradebot.btc_supervised_session import inspect_btc_session_candidate
from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.fire_account_guard import require_flat_demo_account_for_configuration
from tradebot.fire_commission_preflight import _services_active, _fire_disabled
from tradebot.operator_account_mode import read_manual_mode

APPROVAL_PHRASE = "EXECUTE ONE BTC DEMO FIRE"
ATTEMPT_FILE = "btc-demo-supervised-attempt.lock"


def readonly_btc_commission_preflight(
        exchange, data_dir, *, services=_services_active,
        dashboard_disabled=_fire_disabled,
        session_fn=inspect_btc_session_candidate,
        recent_fn=inspect_recent_btc_window,
        manual_mode_fn=read_manual_mode,
        flat_fn=require_flat_demo_account_for_configuration):
    report = {
        "mode": "supervised_btc_demo_read_only_preflight",
        "status": "blocked", "blockers": [],
        "supervised_session_verified": False,
        "recent_btc_history_local_quality_verified": False,
        "independent_btc_trade_price_verification": False,
        "signed_isolated_margin_verified": False,
        "owner_declared_main_isolated_accepted": False,
        "margin_evidence_source": "owner_declaration_not_broker",
        "account_wide_flatness_verified": False,
        "watchdog_and_collector_active": False,
        "both_dashboard_fire_endpoints_disabled": False,
        "trade_authorized": False, "broker_order_mutations": False,
        "financial_ledger_mutations": False, "archive_mutations": False,
        "ai_calls": 0,
    }
    blocks = report["blockers"]
    if (getattr(exchange, "base_url", None) != DEMO_API
            or getattr(exchange, "allow_orders", None) is not False):
        blocks.append("readonly_delta_demo_client_required")
        return report
    try:
        s = session_fn(exchange, data_dir)
        report["supervised_session_verified"] = (
            type(s) is dict and s.get("status") == "baseline_candidate_review_only"
            and s.get("session_budget_within_limits") is True
            and s.get("trade_authorized") is False)
    except Exception:
        pass
    if not report["supervised_session_verified"]:
        blocks.append("fresh_session_equity_unverified")
    try:
        h = recent_fn(data_dir)
        report["recent_btc_history_local_quality_verified"] = (
            type(h) is dict and h.get("status") == "recent24h_local_candidate_only"
            and h.get("complete_contiguous_24h") is True
            and h.get("retained_bars") == 288
            and h.get("quarantined_bars") == 0
            and h.get("suspect_bars") == 0
            and h.get("trade_authorized") is False)
    except Exception:
        pass
    if not report["recent_btc_history_local_quality_verified"]:
        blocks.append("restricted_btc_recent24h_history_unverified")
    # Demo operator policy: the private 0600 declaration replaces ONLY the
    # API's unavailable margin-mode field. Do not label it broker verified.
    try:
        mode = manual_mode_fn(exchange)
        report["owner_declared_main_isolated_accepted"] = (
            isinstance(mode, dict)
            and mode.get("status") == "owner_declared_not_broker_verified"
            and mode.get("account") == "main"
            and mode.get("declared_mode") == "isolated"
            and mode.get("broker_margin_verified") is False
            and mode.get("trade_authorized") is False)
    except Exception:
        pass
    if not report["owner_declared_main_isolated_accepted"]:
        blocks.append("owner_main_isolated_declaration_missing_or_expired")
    else:
        try:
            exposure = flat_fn(exchange)
            report["account_wide_flatness_verified"] = (
                type(exposure) is dict
                and exposure.get("account_flat_verified") is True
                and exposure.get("open_positions") == 0
                and exposure.get("open_orders") == 0
                and set(exposure.get("checked_markets", ())) ==
                    {"BTCUSD", "XAUTUSD"})
        except Exception:
            pass
        if not report["account_wide_flatness_verified"]:
            blocks.append("account_wide_exposure_unverified")
    try:
        report["watchdog_and_collector_active"] = services() is True
    except Exception:
        pass
    if not report["watchdog_and_collector_active"]:
        blocks.append("independent_protection_services_unverified")
    try:
        report["both_dashboard_fire_endpoints_disabled"] = (
            dashboard_disabled() is True)
    except Exception:
        pass
    if not report["both_dashboard_fire_endpoints_disabled"]:
        blocks.append("existing_dashboard_fire_not_disabled_or_unavailable")
    if not blocks:
        report["status"] = "operator_review_candidate_only"
    report["blockers"] = sorted(set(blocks))
    return report


def run_operator_btc_commission(
        data_dir, *, execute=False, approval=None,
        broker_factory=DeltaDemo,
        readiness=readonly_btc_commission_preflight,
        controller_factory=SupervisedBTCController):
    root = Path(data_dir)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Trusted original data directory required")
    root = root.resolve()
    broker = broker_factory(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False)
    report = readiness(broker, root)
    if not isinstance(report, dict):
        raise ValueError("Invalid supervised pilot readiness")
    allowed = (
        report.get("status") == "operator_review_candidate_only"
        and report.get("blockers") == []
        and report.get("supervised_session_verified") is True
        and report.get("recent_btc_history_local_quality_verified") is True
        and report.get("signed_isolated_margin_verified") is False
        and report.get("owner_declared_main_isolated_accepted") is True
        and report.get("margin_evidence_source") == "owner_declaration_not_broker"
        and report.get("account_wide_flatness_verified") is True
        and report.get("watchdog_and_collector_active") is True
        and report.get("both_dashboard_fire_endpoints_disabled") is True
        and report.get("trade_authorized") is False)
    marker = root / ATTEMPT_FILE
    consumed = os.path.lexists(marker)
    if not execute:
        return {
            "mode": "read_only",
            "can_request_operator_approval": allowed and not consumed,
            "one_shot_consumed": consumed,
            "blockers": list(report.get("blockers") or []) +
                (["btc_commission_attempt_consumed"] if consumed else []),
            "trade_authorized": False, "order_submitted": False,
        }
    if not allowed or consumed:
        raise ValueError("Supervised BTC demo execution not cleared")
    if approval != APPROVAL_PHRASE:
        raise ValueError("Exact local operator consent required")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(marker, flags, 0o600)
    try:
        os.write(fd, b"one-attempt BTC DEMO supervised commissioning\n")
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    desk = controller_factory(
        root / "fire-ops.sqlite", enabled=True, spawn=lambda task: task())
    accepted, reason = desk.start()
    state = desk.snapshot()
    return {
        "mode": "one_attempt_supervised_btc_demo",
        "one_shot_consumed": True, "request_accepted": accepted,
        "reason": reason, "status": state.get("status"),
        "order_submitted": state.get("orders_submitted") is True,
        "protection_verified": state.get("protection_verified") is True,
        "liquidation_verified": state.get("liquidation_verified") is True,
        "press": state.get("press"), "trade_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",
                        default=os.getenv("TRADEBOT_DASHBOARD_DATA", "data"))
    parser.add_argument("--execute-one-btc-demo", action="store_true")
    args = parser.parse_args(argv)
    approval = None
    if args.execute_one_btc_demo:
        if not sys.stdin.isatty():
            parser.error("Interactive local operator terminal required")
        print("DELTA INDIA DEMO BTCUSD ONLY. Dashboard FIRE remains disabled.")
        print("May submit one demo market order with broker-side brackets.")
        print("GPT-6 can choose WAIT. Never retry an ambiguous order.")
        approval = input("Type " + APPROVAL_PHRASE + " to continue: ")
    try:
        result = run_operator_btc_commission(
            args.data_dir, execute=args.execute_one_btc_demo,
            approval=approval)
    except (ValueError, FileExistsError, OSError, RuntimeError):
        print(json.dumps({
            "status": "blocked_or_unconfirmed",
            "action": "manual_operator_review_required"
        }, separators=(",", ":")))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("mode") == "read_only" or result.get("request_accepted") else 2


if __name__ == "__main__":
    raise SystemExit(main())
