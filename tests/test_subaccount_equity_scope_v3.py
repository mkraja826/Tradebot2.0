import tempfile
import unittest
from pathlib import Path

from tradebot.equity_policy_core import EquityRiskError
from tradebot.subaccount_equity_scope_v3 import child_equity_guard, scoped_equity_ledger


class SubaccountEquityScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.parent = self.root / "fire-equity-risk.sqlite"
        self.parent.touch()
        self.btc = self.root / "btc-isolated" / self.parent.name
        self.gold = self.root / "gold-isolated" / self.parent.name
        for path in (self.btc, self.gold):
            path.parent.mkdir()
            path.touch()

    def test_independent_ledgers_only(self):
        self.assertEqual(scoped_equity_ledger(self.root, "BTCUSD"), self.btc)
        self.assertEqual(scoped_equity_ledger(self.root, "XAUTUSD"), self.gold)
        self.assertEqual(child_equity_guard(self.root, "BTCUSD").path, self.btc)

    def test_legacy_module_alias_preserves_core_identity(self):
        from tradebot import equity_policy_core, portfolio_equity_guard
        from importlib import import_module
        self.assertIs(import_module("tradebot.portfolio_equity_guard"), equity_policy_core)
        self.assertIs(portfolio_equity_guard, equity_policy_core)
        self.assertIs(portfolio_equity_guard.RuntimeEquityGuard,
                      equity_policy_core.RuntimeEquityGuard)
        self.assertIs(portfolio_equity_guard.EquityRiskError, EquityRiskError)

    def test_missing_child_never_falls_back_to_parent(self):
        self.btc.unlink()
        with self.assertRaises(EquityRiskError):
            scoped_equity_ledger(self.root, "BTCUSD")
        self.assertTrue(self.parent.is_file())

    def test_wrong_symbol_is_rejected(self):
        with self.assertRaises(EquityRiskError):
            scoped_equity_ledger(self.root, "MAIN")

    def test_parent_aliases_are_rejected(self):
        self.btc.unlink()
        self.btc.symlink_to(self.parent)
        with self.assertRaises(EquityRiskError):
            scoped_equity_ledger(self.root, "BTCUSD")
        self.btc.unlink()
        self.btc.hardlink_to(self.parent)
        with self.assertRaises(EquityRiskError):
            scoped_equity_ledger(self.root, "BTCUSD")

    def test_cross_child_alias_is_rejected(self):
        self.btc.unlink()
        self.btc.symlink_to(self.gold)
        with self.assertRaises(EquityRiskError):
            scoped_equity_ledger(self.root, "BTCUSD")
