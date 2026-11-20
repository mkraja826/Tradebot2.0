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
from tradebot.fire_market import FireMarket, positions_for_fire
from tradebot.fire_leverage import verify_liquidation_clearance, LeverageRejected
from tradebot.portfolio_equity_guard import PortfolioEquityGuard
from tradebot.fire_execution import (
    EXPOSED, FireTradeStore, active_position, protective_orders_verified
)


def watchdog_tick(exchange, store, *, pause=None):
    if getattr(exchange, "base_url", None) != DEMO_API or not exchange.allow_orders:
        raise ValueError("Only explicitly enabled Delta India DEMO order client allowed")
    latest = store.latest()
    status = latest["status"]
    planning = {"requested", "reasoning", "preflight"}
    if status not in EXPOSED | planning:
        return {"status": "idle_or_terminal", "last_fire_status": status}
    press = latest["press"]

    # The dashboard may be deciding or waiting for a broker response.
    # Never interfere with a fresh entry; after 90s reconcile the durable
    # request and signed remote account status before a status change.
    updated = datetime.fromisoformat(latest["updated_at"])
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    if status in planning | {"submitting", "reconciling", "verifying_protection"} and age < 90:
        return {"status": "waiting_for_fire", "last_fire_status": status}

    # Read-only broker reconciliation first. Never assume a request was
    # rejected merely because the app lost its original HTTP response.
    import sqlite3
    with sqlite3.connect(store.path, timeout=10) as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='fire_entries'"
        ).fetchone()
        row = (db.execute(
            "SELECT receipt FROM fire_entries WHERE press=?", (press,)
        ).fetchone() if exists else None)
    receipt = json.loads(row[0]) if row else None

    if receipt is None:
        # The durable entry layer always commits its order intent before
        # sending a POST. Without such a receipt, signed flatness evidence is
        # required to mark the stale request aborted. Never close a position
        # of unknown ownership merely because a browser worker disappeared.
        positions = positions_for_fire(exchange)
        orders = exchange.open_orders()
        if (isinstance(positions, list) and isinstance(orders, list) and
                not orders and all(
                    isinstance(item, dict) and
                    str(item.get("size")) in ("0", "0.0", "0.00") for item in positions)):
            store.update(press, "aborted_flat", orders_submitted=False,
                         protection_verified=False,
                         reason_code="stale_request_without_broker_post")
            return {"status": "aborted_flat"}
        store.update(press, "exposure_unknown",
                     reason_code="missing_durable_broker_receipt")
        return {"status": "manual_reconciliation_required"}

    product_id = receipt["product_id"]
    if isinstance(exchange, FireMarket) and exchange.product_id != product_id:
        raise ValueError("Watchdog receipt market mismatch")
    position = active_position(exchange, product_id)
    orders = exchange.open_orders()
    if position is None and not orders:
        store.update(press, "flat_verified",
                     protection_verified=False,
                     reason_code="verified_no_position_or_orders")
        return {"status": "flat_verified"}

    plan = receipt["plan"]
    # Signed parent order lookup establishes what actually filled. The
    # presence of two similar-looking stops alone is not proof of this FIRE.
    parent = exchange.order_by_client_id(press)
    parent_filled = (
        isinstance(parent, dict) and
        parent.get("client_order_id") == press and
        str(parent.get("product_id")) == str(product_id) and
        parent.get("id") == receipt.get("order_id") and
        parent.get("state") == "closed" and
        str(parent.get("unfilled_size")) == "0"
    )
    intended_size = (plan["contracts"] if plan["direction"] == "LONG"
                     else -plan["contracts"])
    position_matches = (
        position is not None and str(position.get("size")) == str(intended_size)
    )
    confirmed = (parent_filled and position_matches and
                 protective_orders_verified(orders, product_id=product_id,
                                            plan=plan))
    if confirmed:
        try:
            proof = verify_liquidation_clearance(exchange, product_id, plan, position)
        except (LeverageRejected, KeyError, TypeError):
            confirmed = False
        else:
            store.update(press, "protected_active", protection_verified=True, **proof)
            return {"status": "protected_active"}

    # A position with incomplete brackets is not safe to abandon when the
    # browser closes, but this automated emergency closeout may still fail.
    store.update(press, "exposure_unknown", protection_verified=False,
                 reason_code="bracket_missing_or_position_changed")
    try:
        if isinstance(exchange, FireMarket):
            exchange.close_exposure(pause or time.sleep)
        else:
            DemoExecutor(exchange, schedule="crypto-24x7",
                         journal_path=str(Path(store.path).parent / "trades.jsonl"),
                         pause=pause or time.sleep).closeout(max_attempts=3)
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
    markets = [(FireTradeStore(path), FireMarket(symbol,
                api_key=os.environ.get("DELTA_DEMO_API_KEY", ""),
                api_secret=os.environ.get("DELTA_DEMO_API_SECRET", ""), allow_orders=True))
               for symbol, path in (("BTCUSD", args.database),
                                    ("XAUTUSD", Path(args.database).with_name("fire-xaut.sqlite")))]
    equity_guard = PortfolioEquityGuard(Path(args.database).parent / "fire-equity-risk.sqlite")
    while True:
        # Read-only sampling: maintain true UTC day/week opening checkpoints
        # even while no FIRE trade is requested. Never interrupt SL/TP protection.
        try:
            latest = equity_guard.latest_observed_us()
            if latest is None or time.time()*1000000 - latest >= 60*1000000:
                equity_guard.observe_signed_demo(markets[0][1])
        except Exception:
            print(json.dumps({"status": "equity_evidence_unavailable",
                              "action": "new_fire_blocked_until_verified"}), flush=True)
        for store, exchange in markets:
            try:
                state = watchdog_tick(exchange, store)
            except Exception:
                state = {"status": "broker_reconciliation_unavailable",
                         "action": "human_attention_required"}
            print(json.dumps({"symbol": exchange.symbol, **state}), flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
