"""Offline tests for durable factual evidence and candidate-only learning."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tradebot.trade_memory import MemoryError, TradeMemory


class LearningMemoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "trade-learning.sqlite"
        self.store = TradeMemory(self.path)
        self.trade = "btc-example1"

    def record(self):
        return self.store.append_event(
            self.trade, "position_first_observed",
            {"symbol": "BTCUSD", "product_id": 1,
             "size": "1", "bid": "990", "ask": "991",
             "mark_price": "990.5", "observed_at": "2026-11-19T00:00:00Z"},
            event_id="evt-1", observed_at="2026-11-19T00:00:00Z")

    def test_append_only_idempotence_and_private_permissions(self):
        first = self.record()
        self.assertEqual(first, "evt-1")
        again = self.store.append_event(
            self.trade, "position_first_observed",
            {"symbol": "BTCUSD", "product_id": 1,
             "size": "1", "bid": "990", "ask": "991",
             "mark_price": "990.5", "observed_at": "2026-11-19T00:00:00Z"},
            event_id="evt-1")
        self.assertEqual(first, again)
        self.assertEqual(len(self.store.events(self.trade)), 1)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE events SET kind='hacked' WHERE event_id='evt-1'")
            db.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM events WHERE event_id='evt-1'")

    def test_conflicting_ids_and_sensitive_keys_are_rejected(self):
        self.record()
        with self.assertRaises(MemoryError):
            self.store.append_event(
                self.trade, "position_first_observed",
                {"symbol": "ETHUSD"}, event_id="evt-1")
        for payload in (
            {"api_secret": "leak"}, {"raw_response": "leak"},
            {"mark_price": {"authorization": "token"}},
        ):
            with self.subTest(payload=payload), self.assertRaises(MemoryError):
                self.store.append_event(self.trade, "position_observed", payload)

    def test_candidates_never_enter_fire_context(self):
        event_id = self.record()
        self.assertTrue(self.store.reserve_review("entry-btc-example1", self.trade, "entry"))
        content = [{
            "hypothesis": "Volume confirmation may have been insufficient",
            "counterevidence": "A similar breakout can succeed in trends",
            "applicable_when": "Only in historically similar market regimes",
            "confidence": 0.42,
            "evidence_refs": [event_id],
        }]
        self.assertEqual(self.store.store_candidates(
            "entry-btc-example1", self.trade, content), 1)
        self.store.finish_review("entry-btc-example1", "completed", token_count=87)
        self.assertEqual(len(self.store.lessons(status="candidate")), 1)
        self.assertEqual(self.store.fire_advisories(), [])
        with self.assertRaises(MemoryError):
            self.store.store_candidates("entry-btc-example1", self.trade, content)

    def test_hallucinated_evidence_never_becomes_a_lesson(self):
        self.record()
        self.store.reserve_review("entry-btc-example1", self.trade, "entry")
        with self.assertRaises(MemoryError):
            self.store.store_candidates("entry-btc-example1", self.trade, [{
                "hypothesis": "Unknown evidence must not be trusted",
                "counterevidence": "There may be contradictory data",
                "applicable_when": "Only when the same conditions recur",
                "confidence": 0.7,
                "evidence_refs": ["made-up-id"],
            }])
        self.assertEqual(self.store.lessons(), [])

    def test_review_reservation_prevents_duplicate_paid_requests(self):
        self.record()
        self.assertTrue(self.store.reserve_review("entry-btc-example1", self.trade, "entry"))
        self.assertFalse(self.store.reserve_review("entry-btc-example1", self.trade, "entry"))
        self.store.finish_review("entry-btc-example1", "provider_failed")
        self.assertFalse(self.store.reserve_review("entry-btc-example1", self.trade, "entry"))
        for index in range(11):
            self.assertTrue(self.store.reserve_review(
                "checkpoint-btc-example1-" + str(index), self.trade, "checkpoint"))
        self.assertFalse(self.store.reserve_review(
            "checkpoint-btc-example1-11", self.trade, "checkpoint"))

    def test_watch_state_is_durable_on_restart(self):
        self.store.save_watch_state(
            trade_id=self.trade, active=True, size="2", mark="50000",
            observed_at="2026-11-19T00:00:00Z", review_mark="50000",
            review_at="2026-11-19T00:00:00Z")
        reloaded = TradeMemory(self.path)
        self.assertEqual(reloaded.watch_state()["trade_id"], self.trade)
        self.assertEqual(reloaded.watch_state()["last_size"], "2")


if __name__ == "__main__":
    unittest.main()
