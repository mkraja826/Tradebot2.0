"""One-shot, operator-approved Gold commissioning via existing durable FIRE.

This command cannot trade autonomously. Without BOTH a CLI execute switch
and a typed local operator confirmation it is entirely read-only. The
web dashboard FIRE setting remains disabled. The authorized path invokes the
existing GPT-6 FIRE controller, which may choose WAIT, requires a single
contract and relies on its independent receipt-linked watchdog.

Do NOT run the execution option until an operator expressly approves a
supervised, one-contract Delta India DEMO trial.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from tradebot.delta import DeltaDemo
from tradebot.fire_commission_preflight import commissioning_preflight
from tradebot.fire_execution import FireDemoController

APPROVAL_PHRASE = "EXECUTE ONE GOLD DEMO FIRE"
ATTEMPT_FILE = "gold-demo-commission-attempt.lock"


def run_operator_commission(
    data_dir, *, execute=False, approval=None,
    broker_factory=DeltaDemo,
    readiness=commissioning_preflight,
    controller_factory=FireDemoController,
):
    """Return a sanitized summary. Only execute=True AND typed confirmation
    can create the one-shot marker and call the existing FIRE controller.
    """
    root = Path(data_dir).resolve()
    # Never create or migrate the receipt folder during a read-only check.
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Existing trusted receipt directory required")
    broker = broker_factory(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False,
    )
    report = readiness(broker, root)
    if not isinstance(report, dict):
        raise ValueError("Invalid commissioning readiness result")
    allowed = (
        report.get("ready_for_supervised_operator_review") is True
        and report.get("broker_flat_two_samples") is True
        and report.get("both_fire_endpoints_disabled") is True
        and report.get("watchdog_and_dashboard_active") is True
        and report.get("trade_authorized") is False
        and report.get("broker_liquidation_price_verified") is False
        and report.get("blockers") == []
    )
    if not execute:
        return dict(
            mode="read_only", can_request_operator_approval=allowed,
            trade_authorized=False, order_submitted=False,
            blockers=list(report.get("blockers") or []),
        )
    if not allowed:
        raise ValueError("Commission readiness gate not passed")
    if approval != APPROVAL_PHRASE:
        raise ValueError("Exact operator confirmation not supplied")
    # Exclusive, permanent marker: never automatically repeat after a
    # crash, disconnect, timeout, ambiguity or a GPT-6 WAIT.
    marker = root / ATTEMPT_FILE
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(marker, flags, 0o600)
    try:
        os.write(fd, b"one-shot Gold DEMO operator commissioning attempt\n")
        os.fsync(fd)
    finally:
        os.close(fd)
    # Use the exact production FIRE receipt DB watched independently.
    # Running inline keeps the CLI attached through the first protection check.
    desk = controller_factory(
        root / "fire-xaut.sqlite", enabled=True, symbol="XAUTUSD",
        spawn=lambda task: task(),
    )
    accepted, reason = desk.start()
    state = desk.snapshot()
    # No attempt to interpret 'accepted' as a filled or protected trade.
    return dict(
        mode="supervised_gold_demo", one_shot_consumed=True,
        request_accepted=accepted, reason=reason,
        status=state.get("status"), order_submitted=state.get("orders_submitted") is True,
        protection_verified=state.get("protection_verified") is True,
        liquidation_verified=state.get("liquidation_verified") is True,
        press=state.get("press"), trade_authorized=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", default=os.getenv("TRADEBOT_DASHBOARD_DATA", "data")
    )
    parser.add_argument(
        "--execute-one-gold-demo", action="store_true",
        help="Request one operator-confirmed, GPT-6-decided Gold demo FIRE",
    )
    args = parser.parse_args(argv)
    approval = None
    if args.execute_one_gold_demo:
        if not sys.stdin.isatty():
            parser.error("An interactive operator terminal is required")
        print("DELTA INDIA DEMO ONLY. BTC/GOLD DASHBOARD FIRE STAYS DISABLED.")
        print("This may submit one XAUTUSD market entry with broker brackets.")
        print("GPT-6 may choose WAIT. A submission is NOT proof of protection.")
        approval = input("Type " + APPROVAL_PHRASE + " to proceed: ")
    try:
        outcome = run_operator_commission(
            args.data_dir, execute=args.execute_one_gold_demo,
            approval=approval,
        )
    except (ValueError, FileExistsError, OSError):
        # Do not expose broker credentials or provider exception bodies.
        print(json.dumps({"status": "blocked_or_unconfirmed",
                          "action": "operator_review_required"},
                         separators=(",", ":")))
        return 2
    print(json.dumps(outcome, sort_keys=True, separators=(",", ":")))
    return 0 if outcome.get("mode") == "read_only" or outcome.get("request_accepted") else 2


if __name__ == "__main__":
    raise SystemExit(main())
