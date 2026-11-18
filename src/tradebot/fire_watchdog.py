"""Independent, restart-safe Delta India Demo FIRE bracket and flatness watchdog.

Only watches order IDs already linked to a user-initiated FIRE. Never opens a
position, requests AI, or makes a strategy decision. If a known FIRE position
loses protective SL/TP, attempts a BTC-only reduce-only closeout.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.execution import DemoExecutor
from tradebot.fire_execution import (
    EXPOSED, FireTradeStore, active_position, protective_orders_verified
)


def watchdog_tick(exchange, store, *, pause=None):
    if getattr(exchange, "base_url", None) != DEMO_API or not exchange.allow_orders:
        raise ValueError("Only explicitly enabled Delta India DEMO order client allowed")
    latest = store.latest()
    status = latest["status"]
    if status not in EXPOSED:
        return {"status": "idle_or_terminal", "last_fire_status": status}
    press = latest["press"]

    # The dashboard may be in the middle of model analysis / broker POST.
    # Do not interfere with an in-progress entry. After 90s the submission
    # can be treated as uncertain and independently inspected.
    updated = datetime.fromisoformat(latest["updated_at"])
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    if status in {"submitting", "reconciling", "verifying_protection"} and age < 90:
        return {"status": "waiting_for_fire", "last_fire_status": status}

    # Read-only broker reconciliation first. Never assume a request was
    # rejected merely because the app lost its original HTTP response.
    import sqlite3
    with sqlite3.connect(store.path, timeout=10) as db:
        row = db.execute(
            "SELECT receipt FROM fire_entries WHERE press=?", (press,)
        ).fetchone()
    receipt = json.loads(row[0]) if row else None

    if receipt is None:
        # Never close unknown human/other-bot positions with a guessed ID.
        if status in {"submitting", "reconciling"}:
            store.update(press, "exposure_unknown",
                         reason_code="missing_durable_broker_receipt")
        return {"status": "manual_reconciliation_required",
                "last_fire_status": store.latest()["status"]}

    product_id = receipt["product_id"]
    position = active_position(exchange, product_id)
    orders = exchange.open_orders()
    if position is None and not orders:
        store.update(press, "flat_verified",
                     protection_verified=False,
                     reason_code="verified_no_position_or_orders")
        return {"status": "flat_verified"}

    plan = receipt["plan"]
    confirmed = (position is not None and
                 protective_orders_verified(orders, product_id=product_id,
                                            plan=plan))
    if confirmed:
        store.update(press, "protected_active", protection_verified=True)
        return {"status": "protected_active"}

    # A position with incomplete brackets is not safe to abandon when the
    # browser closes, but this automated emergency closeout may still fail.
    store.update(press, "exposure_unknown", protection_verified=False,
                 reason_code="bracket_missing_or_position_changed")
    try:
        DemoExecutor(
            exchange, schedule="crypto-24x7",
            journal_path=str(Path(store.path).parent / "trades.jsonl"),
            pause=pause or time.sleep,
        ).closeout(max_attempts=3)
        store.update(press, "flat_verified",
                     protection_verified=False,
                     reason_code="watchdog_emergency_flat_verified")
        return {"status": "emergency_flat_verified"}
    except Exception:
        return {"status": "exposure_unknown",
                "action": "human_attention_required"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/fire-ops.sqlite")
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args(argv)
    if not 5 <= args.interval <= 60:
        parser.error("interval must be 5..60 seconds")
    store = FireTradeStore(args.database)
    exchange = DeltaDemo(
        api_key=os.environ.get("DELTA_DEMO_API_KEY", ""),
        api_secret=os.environ.get("DELTA_DEMO_API_SECRET", ""),
        allow_orders=True,
    )
    while True:
        try:
            state = watchdog_tick(exchange, store)
        except Exception:
            state = {"status": "broker_reconciliation_unavailable",
                     "action": "human_attention_required"}
        # Never print raw exchange responses or secrets.
        print(json.dumps(state, separators=(",", ":")), flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
