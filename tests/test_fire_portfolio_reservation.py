"""No two independent FIRE markets may acquire the same demo account."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from tradebot.fire_execution import FireTradeError, FireTradeStore
from tradebot.fire_portfolio_reservation import FirePortfolioReservation


class FirePortfolioReservationTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.btc_store = FireTradeStore(self.root / "fire-ops.sqlite")
        self.gold_store = FireTradeStore(self.root / "fire-xaut.sqlite")
        self.gate = FirePortfolioReservation(self.root)

    @staticmethod
    def inject_older_receipt(store, status):
        # Deliberately craft a legacy/out-of-order historical ledger. Normal
        # store admission prevents creating such overlapping reservations.
        press = uuid4().hex
        past = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        with sqlite3.connect(store.path) as db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (press, past, past, status, "{}"))
            db.commit()
        return press

    def test_same_account_blocks_second_symbol_until_confirmed_flat(self):
        btc = self.btc_store.reserve()
        self.assertTrue(self.gate.claim("BTCUSD", btc, self.btc_store.path))
        gold = self.gold_store.reserve()
        self.assertFalse(self.gate.claim("XAUTUSD", gold, self.gold_store.path))
        self.btc_store.update(btc, "protected_active")
        self.assertFalse(self.gate.claim("XAUTUSD", gold, self.gold_store.path))
        self.btc_store.update(btc, "flat_verified")
        self.assertTrue(self.gate.claim("XAUTUSD", gold, self.gold_store.path))
        self.assertFalse(self.gate.claim("BTCUSD", btc, self.btc_store.path))

    def test_restarts_cannot_erase_unresolved_claim(self):
        btc = self.btc_store.reserve()
        self.assertTrue(self.gate.claim("BTCUSD", btc, self.btc_store.path))
        restarted = FirePortfolioReservation(self.root)
        gold = self.gold_store.reserve()
        self.assertFalse(restarted.claim("XAUTUSD", gold, self.gold_store.path))
        self.assertFalse(restarted.claim("BTCUSD", btc, self.btc_store.path))

    def test_legacy_exposed_receipt_blocks_new_installation(self):
        btc = self.btc_store.reserve()
        gold = self.gold_store.reserve()
        self.btc_store.update(btc, "exposure_unknown")
        self.assertFalse(self.gate.claim("XAUTUSD", gold, self.gold_store.path))

    def test_market_reserve_blocks_hidden_older_unresolved_even_after_flat_latest(self):
        newest = self.btc_store.reserve()
        self.btc_store.update(newest, "flat_verified")
        hidden = self.inject_older_receipt(self.btc_store, "exposure_unknown")
        with self.assertRaisesRegex(FireTradeError, "broker reconciliation"):
            self.btc_store.reserve()
        self.btc_store.update(hidden, "flat_verified")
        self.assertIsNotNone(self.btc_store.reserve())

    def test_market_reserve_unknown_legacy_status_also_blocks(self):
        newest = self.gold_store.reserve()
        self.gold_store.update(newest, "flat_verified")
        hidden = self.inject_older_receipt(self.gold_store, "legacy_unrecognized")
        with self.assertRaisesRegex(FireTradeError, "broker reconciliation"):
            self.gold_store.reserve()
        self.gold_store.update(hidden, "flat_verified")
        self.assertIsNotNone(self.gold_store.reserve())

    def test_older_exposed_btc_blocks_new_gold_despite_newer_terminal_receipt(self):
        newest = self.btc_store.reserve()
        self.btc_store.update(newest, "flat_verified")
        hidden = self.inject_older_receipt(self.btc_store, "protected_active")
        gold = self.gold_store.reserve()
        self.assertFalse(self.gate.claim("XAUTUSD", gold, self.gold_store.path))
        self.btc_store.update(hidden, "flat_verified")
        self.assertTrue(self.gate.claim("XAUTUSD", gold, self.gold_store.path))

    def test_older_unknown_gold_status_blocks_new_btc_despite_terminal_receipt(self):
        newest = self.gold_store.reserve()
        self.gold_store.update(newest, "rejected_no_order")
        hidden = self.inject_older_receipt(self.gold_store, "unknown_legacy_state")
        btc = self.btc_store.reserve()
        self.assertFalse(self.gate.claim("BTCUSD", btc, self.btc_store.path))
        # Only an explicit terminal reconciliation resolves the old barrier.
        self.gold_store.update(hidden, "flat_verified")
        self.assertTrue(self.gate.claim("BTCUSD", btc, self.btc_store.path))

    def test_older_unresolved_same_market_blocks_even_with_current_request(self):
        newest = self.btc_store.reserve()
        self.btc_store.update(newest, "flat_verified")
        hidden = self.inject_older_receipt(self.btc_store, "exposure_unknown")
        current = uuid4().hex
        stamp = datetime.now(timezone.utc).isoformat()
        # Simulate a legacy producer bypassing the per-market reserve check.
        with sqlite3.connect(self.btc_store.path) as db:
            db.execute("INSERT INTO fire_requests VALUES (?,?,?,?,?)",
                       (current, stamp, stamp, "requested", "{}"))
            db.commit()
        self.assertFalse(self.gate.claim("BTCUSD", current, self.btc_store.path))
        self.btc_store.update(hidden, "flat_verified")
        self.assertTrue(self.gate.claim("BTCUSD", current, self.btc_store.path))

    def test_missing_owner_evidence_never_auto_unlocks(self):
        btc = self.btc_store.reserve()
        self.assertTrue(self.gate.claim("BTCUSD", btc, self.btc_store.path))
        self.btc_store.path.unlink()
        gold = self.gold_store.reserve()
        self.assertFalse(self.gate.claim("XAUTUSD", gold, self.gold_store.path))


if __name__ == "__main__":
    unittest.main()
