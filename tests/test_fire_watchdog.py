"""FIRE watchdog reconciles known Demo exposure after browser restarts."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tradebot.delta import DEMO_API
from tradebot.fire_execution import FireTradeStore
from tradebot.fire_watchdog import watchdog_tick


class Broker:
    base_url = DEMO_API
    allow_orders = True

    def __init__(self):
        self.size = 1
        self.orders = [
            {"id": 21, "product_id": 27, "product_symbol": "BTCUSD",
             "bracket_order": True, "state": "pending", "side": "sell",
             "stop_order_type": "stop_loss_order", "stop_price": "62800"},
            {"id": 22, "product_id": 27, "product_symbol": "BTCUSD",
             "bracket_order": True, "state": "pending", "side": "sell",
             "stop_order_type": "take_profit_order", "stop_price": "63750"},
        ]
        self.closeouts = 0

    def btc_positions(self):
        return ([{"product_id": 27, "size": str(self.size),
                  "product_symbol": "BTCUSD"}] if self.size else [])

    def open_orders(self):
        return list(self.orders)

    def cancel_product_orders(self, product_id):
        self.orders = []

    def products(self):
        return [{"id": 27, "symbol": "BTCUSD", "contract_type": "perpetual_futures",
                 "state": "live"}]

    def place_order(self, *, reduce_only, **kwargs):
        assert reduce_only
        self.closeouts += 1
        self.size = 0
        return {"id": 99}


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = FireTradeStore(self.root / "fire-ops.sqlite")
        self.broker = Broker()

    def seed(self, status="protected_active"):
        press = self.store.reserve()
        self.store.update(press, status, model="tb-gpt-6",
                          direction="LONG", contracts=1,
                          stop_loss="62800", take_profit="63750",
                          protection_verified=status == "protected_active",
                          orders_submitted=True)
        with sqlite3.connect(self.store.path) as db:
            db.execute("CREATE TABLE fire_entries(press TEXT PRIMARY KEY, "
                       "status TEXT NOT NULL, receipt TEXT NOT NULL)")
            db.execute("INSERT INTO fire_entries VALUES(?,?,?)", (
                press, "filled", json.dumps({
                    "press": press, "status": "filled", "product_id": 27,
                    "order_id": 1234, "plan": {
                        "direction": "LONG", "contracts": 1,
                        "stop_loss": "62800", "take_profit": "63750",
                    },
                }),
            ))
        return press

    def test_protected_brackets_are_rechecked_after_restart(self):
        self.seed()
        outcome = watchdog_tick(self.broker, FireTradeStore(self.store.path))
        self.assertEqual(outcome["status"], "protected_active")
        self.assertEqual(self.broker.closeouts, 0)
        self.assertTrue(self.store.latest()["protection_verified"])

    def test_missing_take_profit_triggers_reduce_only_emergency_closeout(self):
        self.seed()
        self.broker.orders.pop()
        outcome = watchdog_tick(self.broker, self.store, pause=lambda _: None)
        self.assertEqual(outcome["status"], "emergency_flat_verified")
        self.assertEqual(self.broker.size, 0)
        self.assertEqual(self.broker.closeouts, 1)
        self.assertEqual(self.store.latest()["status"], "flat_verified")
        self.assertFalse(self.store.latest()["protection_verified"])

    def test_stop_triggered_and_position_closed_records_flat(self):
        self.seed()
        self.broker.size = 0
        self.broker.orders = []
        outcome = watchdog_tick(self.broker, self.store)
        self.assertEqual(outcome["status"], "flat_verified")
        self.assertEqual(self.broker.closeouts, 0)

    def test_stale_pretrade_work_is_aborted_without_broker_post(self):
        press = self.store.reserve()
        self.store.update(press, "reasoning", model="tb-gpt-6",
                          orders_submitted=False)
        with sqlite3.connect(self.store.path) as db:
            db.execute("UPDATE fire_requests SET updated_at=? WHERE press=?", (
                (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat(),
                press))
        self.broker.size = 0
        self.broker.orders = []
        outcome = watchdog_tick(self.broker, self.store)
        self.assertEqual(outcome["status"], "aborted_flat")
        self.assertFalse(self.store.latest()["orders_submitted"])

    def test_stale_pretrade_with_existing_exposure_needs_human_review(self):
        press = self.store.reserve()
        self.store.update(press, "reasoning", model="tb-gpt-6",
                          orders_submitted=False)
        with sqlite3.connect(self.store.path) as db:
            db.execute("UPDATE fire_requests SET updated_at=? WHERE press=?", (
                (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat(),
                press))
        outcome = watchdog_tick(self.broker, self.store)
        self.assertEqual(outcome["status"], "manual_reconciliation_required")
        self.assertEqual(self.store.latest()["status"], "exposure_unknown")
        self.assertEqual(self.broker.closeouts, 0)

    def test_idle_watchdog_never_uses_exchange(self):
        self.assertEqual(watchdog_tick(self.broker, self.store)["status"],
                         "idle_or_terminal")

    def test_non_demo_broker_is_rejected(self):
        self.broker.base_url = "https://api.india.delta.exchange"
        with self.assertRaises(ValueError):
            watchdog_tick(self.broker, self.store)


if __name__ == "__main__":
    unittest.main()
