"""Only authenticated BTC isolated account can use public market candles."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tradebot.delta import DEMO_API
from tradebot.fire_btc_supervised_commission import (
    readonly_btc_commission_preflight, _isolated_btc_services_active,
)


class Broker:
    base_url = DEMO_API
    allow_orders = False


class IsolatedBTCPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.child = self.root / "btc-isolated"
        self.child.mkdir()
        self.market_roots = []

    def session(self, broker, data_dir, **kwargs):
        self.assertEqual(data_dir, self.child)
        return {
            "status": "baseline_candidate_review_only",
            "session_budget_within_limits": True,
            "trade_authorized": False,
        }

    def history(self, data_dir):
        self.market_roots.append(Path(data_dir))
        return {
            "status": "recent24h_local_candidate_only",
            "complete_contiguous_24h": True,
            "retained_bars": 288,
            "quarantined_bars": 0,
            "suspect_bars": 0,
            "trade_authorized": False,
        }

    @staticmethod
    def account_flat(broker):
        return {"account_flat_verified": True,
                "open_positions": 0, "open_orders": 0,
                "checked_markets": ["BTCUSD", "XAUTUSD"]}

    def test_child_signed_margin_and_public_only_market_source(self):
        with patch("tradebot.fire_btc_supervised_commission.signed_account_margin_mode",
                   return_value="isolated"):
            report = readonly_btc_commission_preflight(
                Broker(), self.child,
                services=lambda: True,
                dashboard_disabled=lambda: True,
                session_fn=self.session,
                recent_fn=self.history,
                manual_mode_fn=lambda b: self.fail("main account declaration used"),
                flat_fn=self.account_flat,
                allow_daily_loss_warning=True,
                allow_portfolio_loss_warnings=True,
                allow_signed_subaccount=True)
        self.assertEqual(report["status"], "operator_review_candidate_only")
        self.assertEqual(report["blockers"], [])
        self.assertTrue(report["signed_isolated_margin_verified"])
        self.assertFalse(report["owner_declared_main_isolated_accepted"])
        self.assertEqual(report["margin_evidence_source"], "signed_parent_subaccount")
        self.assertEqual(self.market_roots, [self.root])
        self.assertFalse(report["trade_authorized"])

    def test_sibling_or_wrong_data_root_never_accepted(self):
        with patch("tradebot.fire_btc_supervised_commission.signed_account_margin_mode",
                   return_value="isolated"):
            report = readonly_btc_commission_preflight(
                Broker(), self.root,
                services=lambda: True,
                dashboard_disabled=lambda: True,
                session_fn=lambda *args, **kwargs: {
                    "status": "baseline_candidate_review_only",
                    "session_budget_within_limits": True,
                    "trade_authorized": False},
                recent_fn=self.history, flat_fn=self.account_flat,
                allow_signed_subaccount=True)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["recent_btc_history_local_quality_verified"])
        self.assertEqual(self.market_roots, [])

    def test_isolated_service_check_uses_only_matching_btc_services(self):
        names = []
        def run(args, **kwargs):
            names.append(args[-1])
            return type("Process", (), {"returncode": 0})()
        with patch.dict("os.environ", {"TRADEBOT_EXPECTED_DEMO_SUBACCOUNT": "BTC"}):
            with patch("tradebot.fire_btc_supervised_commission.subprocess.run",
                       side_effect=run):
                self.assertTrue(_isolated_btc_services_active())
        self.assertEqual(names, [
            "tradebot2-isolated-demo-monitor@BTC-watchdog.service",
            "tradebot2-isolated-demo-monitor@BTC-equity.service",
            "tradebot2-dashboard.service",
        ])
        with patch.dict("os.environ", {"TRADEBOT_EXPECTED_DEMO_SUBACCOUNT": "GOLD"}):
            self.assertFalse(_isolated_btc_services_active())


if __name__ == "__main__":
    unittest.main()
