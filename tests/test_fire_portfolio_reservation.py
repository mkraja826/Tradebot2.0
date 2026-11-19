"""No two independent FIRE markets may acquire the same demo account."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from tradebot.fire_execution import FireTradeStore
from tradebot.fire_portfolio_reservation import FirePortfolioReservation


class FirePortfolioReservationTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.btc_store = FireTradeStore(self.root / "fire-ops.sqlite")
        self.gold_store = FireTradeStore(self.root / "fire-xaut.sqlite")
        self.gate = FirePortfolioReservation(self.root)

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

    def test_missing_owner_evidence_never_auto_unlocks(self):
        btc = self.btc_store.reserve()
        self.assertTrue(self.gate.claim("BTCUSD", btc, self.btc_store.path))
        self.btc_store.path.unlink()
        gold = self.gold_store.reserve()
        self.assertFalse(self.gate.claim("XAUTUSD", gold, self.gold_store.path))


if __name__ == "__main__":
    unittest.main()
