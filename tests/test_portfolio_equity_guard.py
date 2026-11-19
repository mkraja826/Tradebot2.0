"""The equity-loss guard must fail closed on weak evidence or limits."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from tradebot.portfolio_equity_guard import PortfolioEquityGuard, EquityRiskError


def dt(day, hour=0, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)


class PortfolioEquityGuardTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "equity.sqlite"
        self.guard = PortfolioEquityGuard(self.path)

    def seed(self):
        # Nov 16, 2026 is Monday. Opening readings must be actual observations.
        self.guard.observe("1000", at=dt(16,0,1))
        self.guard.observe("1000", at=dt(19,0,1))

    def test_missing_opening_checkpoint_blocks_new_entries(self):
        result = self.guard.observe("1000",at=dt(19,14,0))
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"],"missing_opening_equity_checkpoint")

    def test_verified_openings_and_restart_allow_provisional_admission(self):
        self.seed()
        new = PortfolioEquityGuard(self.path)
        report = new.require_approved("998",at=dt(19,14,0))
        self.assertTrue(report["approved"])
        self.assertEqual(report["daily_open_equity_usd"],"1000")
        self.assertEqual(report["weekly_open_equity_usd"],"1000")
        self.assertFalse(report["is_reconciled_realized_pnl"])

    def test_daily_two_percent_limit_blocks(self):
        self.seed()
        with self.assertRaisesRegex(EquityRiskError,"loss_limit_daily"):
            self.guard.require_approved("979",at=dt(19,14))

    def test_weekly_five_percent_limit_blocks_without_daily_loss(self):
        self.guard.observe("1100",at=dt(16,0,1))
        self.guard.observe("1000",at=dt(19,0,1))
        with self.assertRaisesRegex(EquityRiskError,"loss_limit_weekly"):
            self.guard.require_approved("999",at=dt(19,14))

    def test_eight_percent_peak_drawdown_blocks_even_if_weekly_open_is_low(self):
        self.guard.observe("1300",at=dt(16,0,1))
        # Friday week starts at 1300; drawdown already exceeds 8%
        self.guard.observe("1200",at=dt(19,0,1))
        result = self.guard.observe("1200",at=dt(19,14))
        self.assertFalse(result["approved"])
        self.assertIn("drawdown",result["reason"])

    def test_conflicting_timestamp_rejected_and_history_immutable(self):
        self.guard.observe("1000",at=dt(16,0,1))
        with self.assertRaisesRegex(EquityRiskError,"Conflicting"):
            self.guard.observe("500",at=dt(16,0,1))
        self.assertEqual(PortfolioEquityGuard(self.path).latest_observed_us(),
                         int(dt(16,0,1).timestamp()*1000000))

    def test_signed_demo_only(self):
        fake=Mock(base_url="https://api.india.delta.exchange")
        with self.assertRaisesRegex(EquityRiskError,"Non-demo"):
            self.guard.observe_signed_demo(fake)
        fake.wallet_balances.assert_not_called()


if __name__ == "__main__":
    unittest.main()
