"""Synthetic-only exchange observations; review callback cannot trade."""
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path

from tradebot.delta import DEMO_API
from tradebot.trade_learning_watch import LearningWatcher, LearningWatchError
from tradebot.trade_memory import TradeMemory


NOW = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)


class FakeReadOnlyDemo:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self):
        self.size = 0
        self.pending = []
        self.price = "63400"
        self.fail = False
        self.orders_posted = 0
        self.now = NOW

    def ticker(self, symbol):
        if self.fail:
            raise TimeoutError("broken secret auth body")
        return {"symbol": symbol, "product_id": 13,
                "timestamp": int(self.now.timestamp()),
                "quotes": {"best_bid": "63400", "best_ask": "63400.5"},
                "mark_price": self.price}

    def btc_positions(self):
        if self.size == 0:
            return []
        return [{"product_id": 13, "size": str(self.size),
                 "entry_price": "63200"}]

    def open_orders(self):
        return self.pending

    def place_order(self, **kwargs):
        self.orders_posted += 1
        raise AssertionError("Kimi watcher may never place an order")


class WatchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = TradeMemory(Path(tmp.name) / "learning.db")
        self.exchange = FakeReadOnlyDemo()
        self.clock = [NOW]
        self.review_notifications = []
        self.watcher = LearningWatcher(
            self.exchange, self.store,
            on_review=lambda trade, phase, key: self.review_notifications.append(
                (trade, phase, key)),
            now=lambda: self.clock[0],
        )

    def step(self, delta_minutes=0):
        self.clock[0] += timedelta(minutes=delta_minutes)
        self.exchange.now = self.clock[0]
        return self.watcher.poll()

    def test_idle_only_reads_no_paid_reviews(self):
        result = self.step()
        self.assertEqual(result["status"], "flat_idle")
        self.assertEqual(self.review_notifications, [])
        self.assertEqual(self.exchange.orders_posted, 0)

    def test_entry_checkpoint_exit_and_persistence(self):
        self.exchange.size = 2
        first = self.step()
        self.assertEqual(first["status"], "active_first_observed")
        self.assertEqual(self.review_notifications[0][1], "entry")
        self.assertEqual(len(self.store.events(first["trade_id"])), 1)

        second = self.step(delta_minutes=5)
        self.assertFalse(second["checkpoint"])
        self.assertEqual(len(self.review_notifications), 1)

        self.exchange.price = "63800"  # 0.63% from initial price -> checkpoint
        third = self.step(delta_minutes=6)
        self.assertTrue(third["checkpoint"])
        self.assertEqual(self.review_notifications[-1][1], "checkpoint")

        self.exchange.size = 0
        self.exchange.pending = [{"id": 1}]
        blocked = self.step(delta_minutes=1)
        self.assertEqual(blocked["status"], "flat_with_pending_orders_unverified")
        self.assertTrue(self.store.watch_state()["active"])

        self.exchange.pending = []
        done = self.step(delta_minutes=1)
        self.assertEqual(done["status"], "flat_observed_not_pnl_verified")
        self.assertEqual(self.review_notifications[-1][1], "exit")
        kinds = [e["kind"] for e in self.store.events(first["trade_id"])]
        self.assertIn("position_first_observed", kinds)
        self.assertIn("position_observed", kinds)
        self.assertIn("position_closed_observed", kinds)
        self.assertFalse(self.store.watch_state()["active"])
        self.assertEqual(self.exchange.orders_posted, 0)

    def test_read_failure_never_marks_position_as_closed(self):
        self.exchange.size = 1
        first = self.step()
        self.exchange.fail = True
        with self.assertRaises(TimeoutError):
            self.step(delta_minutes=1)
        self.assertEqual(self.store.watch_state()["trade_id"], first["trade_id"])
        self.assertTrue(self.store.watch_state()["active"])
        self.assertEqual(len(self.review_notifications), 1)

    def test_restart_uses_same_trade_id(self):
        self.exchange.size = -1
        first = self.step()
        after_restart = LearningWatcher(self.exchange, TradeMemory(self.store.path),
                                       now=lambda: self.clock[0])
        result = after_restart.poll()
        self.assertEqual(result["trade_id"], first["trade_id"])
        self.assertEqual(self.exchange.orders_posted, 0)

    def test_non_demo_or_write_enabled_exchange_is_rejected(self):
        self.exchange.allow_orders = True
        with self.assertRaises(LearningWatchError):
            LearningWatcher(self.exchange, self.store)
        self.exchange.allow_orders = False
        self.exchange.base_url = "https://api.deltaexchange.com"
        with self.assertRaises(LearningWatchError):
            LearningWatcher(self.exchange, self.store)


if __name__ == "__main__":
    unittest.main()
