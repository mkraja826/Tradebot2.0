"""The equity-loss guard must fail closed on weak evidence or limits."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from equity_fixtures import receipt_for
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
        for when in (dt(16,0,1), dt(19,0,1)):
            self.guard.observe_verified_read("1000", receipt_for("1000", when), now=when)

    def test_missing_opening_checkpoint_blocks_new_entries(self):
        result = self.guard.observe("1000",at=dt(19,14,0))
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"],"missing_opening_equity_checkpoint")

    def test_admission_rejects_exact_utc_five_minute_open_boundary(self):
        # Monday's first five minutes are [00:00,00:05), not inclusive of 00:05.
        at = dt(23, 0, 5)
        before = self.guard.latest_observed_us()
        with self.assertRaisesRegex(
                EquityRiskError, "missing_opening_equity_checkpoint"):
            self.guard.require_verified_read(
                "1000", receipt_for("1000", at), now=at)
        self.assertEqual(self.guard.latest_observed_us(), before)
        # Existing loss budget is never reset or a new baseline fabricated.
        observation = self.guard.observe_verified_read(
            "1000", receipt_for("1000", at), now=at)
        self.assertFalse(observation["approved"])
        self.assertEqual(observation["reason"],
                         "missing_opening_equity_checkpoint")
        self.assertIsNone(observation["daily_open_equity_usd"])
        self.assertIsNone(observation["weekly_open_equity_usd"])

    def test_admission_accepts_genuine_last_in_window_microsecond(self):
        at = datetime(2026,11,23,0,4,59,999999,tzinfo=timezone.utc)
        report = self.guard.require_verified_read(
            "1000", receipt_for("1000", at), now=at)
        self.assertTrue(report["approved"])
        self.assertEqual(report["daily_open_equity_usd"], "1000")
        self.assertEqual(report["weekly_open_equity_usd"], "1000")

    def test_verified_openings_and_restart_allow_provisional_admission(self):
        self.seed()
        new = PortfolioEquityGuard(self.path)
        at = dt(19,14,0)
        report = new.require_approved("998", receipt=receipt_for("998", at), now=at)
        self.assertTrue(report["approved"])
        self.assertEqual(report["daily_open_equity_usd"],"1000")
        self.assertEqual(report["weekly_open_equity_usd"],"1000")
        self.assertFalse(report["is_reconciled_realized_pnl"])

    def test_daily_two_percent_limit_blocks(self):
        self.seed()
        with self.assertRaisesRegex(EquityRiskError,"loss_limit_daily"):
            at = dt(19,14)
            self.guard.require_approved("979", receipt=receipt_for("979", at), now=at)

    def test_weekly_five_percent_limit_blocks_without_daily_loss(self):
        for value, at in (("1100", dt(16,0,1)), ("1000", dt(19,0,1))):
            self.guard.observe_verified_read(value, receipt_for(value, at), now=at)
        with self.assertRaisesRegex(EquityRiskError,"loss_limit_weekly"):
            at = dt(19,14)
            self.guard.require_approved("999", receipt=receipt_for("999", at), now=at)

    def test_eight_percent_peak_drawdown_blocks_even_if_weekly_open_is_low(self):
        self.guard.observe("1320",at=dt(16,0,1))
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

    def test_legacy_unsigned_equity_approval_helper_cannot_issue_permission(self):
        self.seed()
        before = self.guard.latest_observed_us()
        with self.assertRaisesRegex(EquityRiskError, "verified_equity_receipt_required"):
            self.guard.require_approved("999", at=dt(19,14))
        with self.assertRaisesRegex(EquityRiskError, "verified_equity_receipt_required"):
            self.guard.require_approved("999")
        self.assertEqual(self.guard.latest_observed_us(), before)

    def test_signed_demo_only(self):
        fake=Mock(base_url="https://api.india.delta.exchange")
        with self.assertRaisesRegex(EquityRiskError,"Non-demo"):
            self.guard.observe_signed_demo(fake)
        fake.wallet_balances.assert_not_called()


if __name__ == "__main__":
    unittest.main()
