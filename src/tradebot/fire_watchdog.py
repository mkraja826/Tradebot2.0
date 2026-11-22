"""Independent, restart-safe Delta India Demo FIRE bracket and flatness watchdog.

Only watches order IDs already linked to a user-initiated FIRE. Never opens a
position, requests AI, or makes a strategy decision. If a known FIRE position
loses protective SL/TP, attempts a BTC-only reduce-only closeout.
"""
import argparse
from datetime import datetime, timezone
from contextlib import closing
import json
import sqlite3
import os
from pathlib import Path
import time

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.execution import DemoExecutor
from tradebot.fire_market import FireMarket, positions_for_fire
from tradebot.fire_leverage import verify_liquidation_clearance, LeverageRejected
from tradebot.equity_monitor import MonitorStore
from tradebot.fire_execution import (
    EXPOSED, FireTradeStore, active_position, protective_orders_verified
)

# Static, non-sensitive runtime identity. Check the current *process* journal
# after an upgrade: a source checkout alone does not prove the daemon reloaded.
WATCHDOG_RUNTIME_VERSION = "watchdog-telemetry-v3-20261122"


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
        # If the prior tick persisted a protection failure and the process
        # crashed while trying reduce-only closeout, we cannot prove whether
        # that closeout or an unrelated broker exit flattened the position.
        # Do not convert the incident into an ordinary no-exposure receipt.
        prior_protection_failure = (
            status == "exposure_unknown"
            and latest.get("reason_code") == "bracket_missing_or_position_changed"
        )
        reason = ("watchdog_protection_failure_flat_verified"
                  if prior_protection_failure else "verified_no_position_or_orders")
        store.update(press, "flat_verified",
                     protection_verified=False,
                     reason_code=reason)
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


def _durable_emergency_receipts(store):
    """Recover any completed watchdog emergency that lacks alert delivery.

    Scan the original private FIRE ledger read-only, including older receipts
    hidden behind a newer terminal press. A crash between broker-confirmed
    flatness and monitor outbox commit must not permanently lose the incident.
    """
    path = Path(store.path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("watchdog_fire_ledger_unavailable")
    with closing(sqlite3.connect(
            path.absolute().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        rows = db.execute(
            "SELECT press,result FROM fire_requests WHERE status='flat_verified' "
            "AND (result LIKE '%watchdog_emergency_flat_verified%' "
            "OR result LIKE '%watchdog_protection_failure_flat_verified%') "
            "ORDER BY created_at ASC LIMIT 1001"
        ).fetchall()
        if len(rows) > 1000:
            raise ValueError("watchdog_unbounded_incident_history")
        out = []
        for press, raw in rows:
            parsed = json.loads(raw)
            if type(parsed) is not dict:
                raise ValueError("watchdog_emergency_receipt_unverified")
            reason = parsed.get("reason_code")
            if reason in ("watchdog_emergency_flat_verified",
                          "watchdog_protection_failure_flat_verified"):
                out.append((press, reason))
        db.rollback()
    return out


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
    monitoring_path = Path(args.database).parent / "fire-monitoring.sqlite"
    monitoring_started = False
    last_monitor_error = None
    # Emit an unmistakable, non-secret startup marker from THIS Python process.
    # If this event does not appear under its own systemd MainPID, the daemon
    # isn't running this source, irrespective of the git checkout on disk.
    print(json.dumps({"event": "watchdog_runtime_initialized",
                      "runtime_version": WATCHDOG_RUNTIME_VERSION,
                      "new_entry_orders_enabled": False}), flush=True)

    # Register a startup state before the first broker sweep. It is explicitly
    # *unverified* until both markets have completed one protective check.
    # A slow/blocked first exchange GET must not masquerade as healthy.
    try:
        initial_monitor = MonitorStore(monitoring_path)
        initial_monitor.start("watchdog")
        initial_monitor.heartbeat("watchdog", "watchdog_protection_unverified")
        monitoring_started = True
    except Exception:
        print(json.dumps({"event": "watchdog_telemetry_unavailable",
                          "action": "protection_loop_continues"}), flush=True)
        last_monitor_error = time.monotonic()

    while True:
        # Protection always runs before optional telemetry. Equity reads run in
        # their own read-only service; a broken equity DB cannot stop this loop.
        healthy = True
        for store, exchange in markets:
            try:
                state = watchdog_tick(exchange, store)
            except Exception:
                state = {"status": "broker_reconciliation_unavailable",
                         "action": "human_attention_required"}
            if state["status"] in {"broker_reconciliation_unavailable", "exposure_unknown",
                                  "manual_reconciliation_required"}:
                healthy = False
            print(json.dumps({"symbol": exchange.symbol, **state}), flush=True)
        try:
            monitoring = MonitorStore(monitoring_path)
            if not monitoring_started:
                monitoring.start("watchdog")
                monitoring_started = True
            # Persist authenticated closeout INCIDENTS before advertising a
            # healthy cycle. A one-off successful emergency exit must remain
            # visible to both off-host and Telegram delivery after restart,
            # even if the monitor collector never polls during that 15s tick.
            for store, _ in markets:
                for emergency_press, reason in _durable_emergency_receipts(store):
                    event = monitoring.record_watchdog_emergency(
                        emergency_press, reason_code=reason)
                    if event is not None:
                        print(json.dumps(event), flush=True)
            monitoring.heartbeat("watchdog", "healthy" if healthy else "watchdog_protection_unverified")
        except Exception:
            tick_at = time.monotonic()
            if last_monitor_error is None or tick_at - last_monitor_error >= 300:
                print(json.dumps({"event": "watchdog_telemetry_unavailable",
                                  "action": "protection_loop_continues"}), flush=True)
                last_monitor_error = tick_at
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
