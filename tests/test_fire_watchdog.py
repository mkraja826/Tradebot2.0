"""FIRE watchdog reconciles known Demo exposure after browser restarts."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from tradebot.delta import DEMO_API
from tradebot.fire_execution import FireTradeStore
from tradebot.fire_watchdog import watchdog_tick, main


class Broker:
    base_url = DEMO_API
    allow_orders = True

    def __init__(self):
        self.size = 1
        self.orders = [
            {"id": 21, "product_id": 27, "product_symbol": "BTCUSD",
             "bracket_order": True, "state": "pending", "side": "sell",
             "stop_order_type": "stop_loss_order", "stop_price": "62800", "size": 1},
            {"id": 22, "product_id": 27, "product_symbol": "BTCUSD",
             "bracket_order": True, "state": "pending", "side": "sell",
             "stop_order_type": "take_profit_order", "stop_price": "63750", "size": 1},
        ]
        self.closeouts = 0

    def btc_positions(self):
        return ([{"product_id": 27, "size": str(self.size),
                  "product_symbol": "BTCUSD", "entry_price": "63214"}] if self.size else [])

    def _request(self, method, path, *, params=None, auth=False):
        if method != "GET" or not auth:
            raise AssertionError("Unexpected broker call")
        if path == "/v2/profile":
            return {"result": {"margin_mode": "isolated"}}
        if path != "/v2/positions/margined":
            raise AssertionError("Unexpected broker path")
        assert params == {"product_ids": "27"}
        return {"result": ([{"product_id": 27, "size": self.size,
                             "margin_mode": "isolated", "entry_price": "63214",
                             "liquidation_price": "60000"}]
                            if self.size else [])}

    def open_orders(self):
        return list(self.orders)

    def order_by_client_id(self, press):
        return {"id": 1234, "client_order_id": press, "product_id": 27,
                "state": "closed", "unfilled_size": 0}

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
                        "direction": "LONG", "contracts": 1, "leverage": 5,
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

    def test_undersized_bracket_never_recovers_protected_status(self):
        self.seed()
        self.broker.orders[0]["size"] = "0"
        outcome = watchdog_tick(self.broker, self.store, pause=lambda _: None)
        self.assertEqual(outcome["status"], "emergency_flat_verified")
        self.assertEqual(self.broker.size, 0)
        self.assertEqual(self.broker.closeouts, 1)
        self.assertEqual(self.store.latest()["status"], "flat_verified")
        self.assertFalse(self.store.latest()["protection_verified"])

    def test_duplicated_bracket_child_requires_emergency_flatness(self):
        self.seed()
        self.broker.orders.append(dict(self.broker.orders[1], id=23))
        outcome = watchdog_tick(self.broker, self.store, pause=lambda _: None)
        self.assertEqual(outcome["status"], "emergency_flat_verified")
        self.assertEqual(self.broker.size, 0)
        self.assertEqual(self.broker.closeouts, 1)
        self.assertFalse(self.store.latest()["protection_verified"])

    def test_extra_same_product_stop_triggers_watchdog_emergency_closeout(self):
        self.seed()
        self.broker.orders.append({
            "id": 23, "product_id": 27, "product_symbol": "BTCUSD",
            "bracket_order": True, "state": "pending", "side": "sell",
            "stop_order_type": "stop_loss_order", "stop_price": "62700",
            "size": 1,
        })
        outcome = watchdog_tick(self.broker, self.store, pause=lambda _: None)
        self.assertEqual(outcome["status"], "emergency_flat_verified")
        self.assertEqual(self.broker.size, 0)
        self.assertEqual(self.broker.closeouts, 1)
        self.assertFalse(self.store.latest()["protection_verified"])

    def test_unrelated_same_product_pending_order_prevents_protected_recovery(self):
        self.seed()
        self.broker.orders.append({
            "id": 23, "product_id": 27, "product_symbol": "BTCUSD",
            "state": "pending", "side": "sell", "size": 1,
        })
        outcome = watchdog_tick(self.broker, self.store, pause=lambda _: None)
        self.assertEqual(outcome["status"], "emergency_flat_verified")
        self.assertEqual(self.broker.size, 0)
        self.assertFalse(self.store.latest()["protection_verified"])

    def test_verified_bracket_exit_allows_immediate_next_manual_press(self):
        previous = self.seed()
        self.broker.size = 0
        self.broker.orders = []
        outcome = watchdog_tick(self.broker, self.store)
        self.assertEqual(outcome["status"], "flat_verified")
        self.assertEqual(self.broker.closeouts, 0)

        self.assertNotEqual(self.store.reserve(), previous)

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

    def test_corrupt_equity_and_failed_telemetry_do_not_interrupt_protection_loop(self):
        (self.root / "fire-equity-risk.sqlite").write_bytes(b"broken equity db")
        fake_market = Mock(symbol="BTCUSD")
        with (patch("tradebot.fire_watchdog.FireMarket", return_value=fake_market),
              patch("tradebot.fire_watchdog.watchdog_tick", return_value={"status":"protected_active"}) as tick,
              patch("tradebot.fire_watchdog.MonitorStore", side_effect=OSError("private failure")),
              patch("tradebot.fire_watchdog.time.sleep", side_effect=KeyboardInterrupt),
              patch("builtins.print") as output):
            with self.assertRaises(KeyboardInterrupt):
                main(["--database",str(self.store.path)])
        self.assertEqual(tick.call_count, 2)
        self.assertIn("protection_loop_continues", str(output.call_args_list))
        self.assertNotIn("private failure", str(output.call_args_list))
        self.assertEqual((self.root / "fire-equity-risk.sqlite").read_bytes(), b"broken equity db")


if __name__ == "__main__":
    unittest.main()
