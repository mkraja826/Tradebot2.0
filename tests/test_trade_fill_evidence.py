"""Offline test: broker-confirmed fills are evidence, never inferred profit."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tradebot.delta import DEMO_API
from tradebot.trade_memory import MemoryError, TradeMemory
from tradebot.trade_fill_evidence import collect_fill_evidence


NOW = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)


def fill(**fields):
    row = {
        "id": "confirmed-17", "created_at": "1795040000000000",
        "product_symbol": "BTCUSD", "side": "buy", "size": "2",
        "price": "64000", "commission": "1.25",
        "settling_asset_symbol": "USD", "order_id": "order-15",
        "account_id": "must-not-store-private-account",
        "debug_provider_text": "must-not-store-secret-text",
    }
    row.update(fields)
    return row


class Broker:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self):
        self.fills = [fill()]
        self.calls = []

    def btc_fills(self, **kwargs):
        self.calls.append(kwargs)
        return self.fills

    def place_order(self, **kwargs):
        raise AssertionError("No broker mutations allowed")


class FillEvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "memory.sqlite"
        self.store = TradeMemory(self.file)
        self.broker = Broker()

    def test_read_only_import_and_idempotent_duplicate(self):
        summary = collect_fill_evidence(self.broker, self.store, now=NOW)
        self.assertEqual(summary["new"], 1)
        self.assertEqual(summary["received"], 1)
        self.assertEqual(summary["confirmed_btc_fills"], 1)
        self.assertEqual(summary["fees_by_asset"], {"USD": "1.25"})
        self.assertFalse(summary["realized_pnl_verified"])
        self.assertFalse(summary["trade_attribution_verified"])
        self.assertFalse(summary["orders_submitted"])
        self.assertEqual(len(self.broker.calls), 1)

        again = collect_fill_evidence(self.broker, TradeMemory(self.file), now=NOW)
        self.assertEqual(again["new"], 0)
        self.assertEqual(again["duplicates"], 1)
        raw = self.file.read_bytes()
        self.assertNotIn(b"must-not-store-private-account", raw)
        self.assertNotIn(b"must-not-store-secret-text", raw)

    def test_incomplete_or_malformed_batch_cannot_commit(self):
        self.broker.fills = [fill(), fill(id="broken", commission="NaN")]
        with self.assertRaises(MemoryError):
            collect_fill_evidence(self.broker, self.store, now=NOW)
        self.assertEqual(self.store.unattributed_fill_summary()["confirmed_btc_fills"], 0)

    def test_conflicting_same_fill_id_is_not_silently_overwritten(self):
        collect_fill_evidence(self.broker, self.store, now=NOW)
        self.broker.fills = [fill(price="65000")]
        with self.assertRaises(MemoryError):
            collect_fill_evidence(self.broker, self.store, now=NOW)
        self.assertEqual(self.store.unattributed_fill_summary()["confirmed_btc_fills"], 1)
        with sqlite3.connect(self.file) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM unattributed_fills")

    def test_error_does_not_turn_into_empty_fills(self):
        def fail(**kwargs):
            raise TimeoutError("connection failed")
        self.broker.btc_fills = fail
        with self.assertRaises(TimeoutError):
            collect_fill_evidence(self.broker, self.store, now=NOW)
        self.assertEqual(self.store.unattributed_fill_summary()["confirmed_btc_fills"], 0)

    def test_demo_only_and_no_write_access(self):
        self.broker.allow_orders = True
        with self.assertRaises(ValueError):
            collect_fill_evidence(self.broker, self.store, now=NOW)
        self.broker.allow_orders = False
        self.broker.base_url = "https://api.deltaexchange.com"
        with self.assertRaises(ValueError):
            collect_fill_evidence(self.broker, self.store, now=NOW)


if __name__ == "__main__":
    unittest.main()
