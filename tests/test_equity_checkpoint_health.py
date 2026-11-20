"""Checkpoint health requires authentic first-five-minute UTC evidence."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tradebot.equity_checkpoint_health import checkpoint_health
from tradebot.portfolio_equity_guard import PortfolioEquityGuard


def utc(day, hour=0, minute=0, second=0):
    return datetime(2026, 11, day, hour, minute, second, tzinfo=timezone.utc)


class CheckpointHealthTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "risk.sqlite"

    def check(self, at):
        return checkpoint_health(self.db, at=at)

    def test_missing_ledger_does_not_create_db(self):
        result = self.check(utc(20, 12))
        self.assertEqual(result["status"], "evidence_unavailable")
        self.assertFalse(self.db.exists())
        self.assertFalse(result["checkpoint_prerequisites_met"])
        self.assertFalse(result["trade_authorized"])

    def test_no_observations_after_window_alerts_both(self):
        PortfolioEquityGuard(self.db)
        result = self.check(utc(20, 12))
        self.assertEqual(result["daily_checkpoint"], "missed_window")
        self.assertEqual(result["weekly_checkpoint"], "missed_window")
        self.assertEqual(result["status"], "checkpoint_missed")
        self.assertEqual(set(result["alert_codes"]), {
            "missed_daily_checkpoint", "missed_weekly_checkpoint",
            "signed_equity_observation_stale"
        })

    def test_utc_monday_open_pending_is_not_falsely_missed(self):
        PortfolioEquityGuard(self.db)
        result = self.check(utc(23, 0, 2))
        self.assertEqual(result["daily_checkpoint"], "pending_window")
        self.assertEqual(result["weekly_checkpoint"], "pending_window")
        self.assertEqual(result["status"], "evidence_stale")
        self.assertNotIn("missed_daily_checkpoint", result["alert_codes"])
        self.assertNotIn("missed_weekly_checkpoint", result["alert_codes"])

    def test_after_window_monday_alerts_immediately(self):
        PortfolioEquityGuard(self.db)
        result = self.check(utc(23, 0, 5, 1))
        self.assertIn("missed_daily_checkpoint", result["alert_codes"])
        self.assertIn("missed_weekly_checkpoint", result["alert_codes"])

    def test_signed_openings_and_recent_observation_are_healthy(self):
        guard = PortfolioEquityGuard(self.db)
        guard.observe("1000", at=utc(16, 0, 1))
        guard.observe("980", at=utc(20, 0, 1))
        guard.observe("975", at=utc(20, 12, 0))
        result = self.check(utc(20, 12, 1))
        self.assertEqual(result["daily_checkpoint"], "verified")
        self.assertEqual(result["weekly_checkpoint"], "verified")
        self.assertEqual(result["status"], "healthy")
        self.assertTrue(result["checkpoint_prerequisites_met"])
        self.assertFalse(result["trade_authorized"])
        self.assertEqual(result["alert_codes"], [])

    def test_monday_open_can_be_recorded_during_window(self):
        guard = PortfolioEquityGuard(self.db)
        guard.observe("995", at=utc(23, 0, 3))
        result = self.check(utc(23, 0, 4))
        self.assertEqual(result["daily_checkpoint"], "verified")
        self.assertEqual(result["weekly_checkpoint"], "verified")
        self.assertTrue(result["checkpoint_prerequisites_met"])

    def test_missing_today_open_is_not_replaced_by_yesterday(self):
        guard = PortfolioEquityGuard(self.db)
        guard.observe("1000", at=utc(16, 0, 1))
        guard.observe("990", at=utc(19, 0, 1))
        guard.observe("988", at=utc(20, 12, 0))
        result = self.check(utc(20, 12, 1))
        self.assertEqual(result["daily_checkpoint"], "missed_window")
        self.assertEqual(result["weekly_checkpoint"], "verified")
        self.assertIn("missed_daily_checkpoint", result["alert_codes"])

    def test_stale_signed_wallet_observation_alert(self):
        guard = PortfolioEquityGuard(self.db)
        guard.observe("1000", at=utc(23, 0, 1))
        result = self.check(utc(23, 0, 5))
        self.assertEqual(result["status"], "evidence_stale")
        self.assertIn("signed_equity_observation_stale", result["alert_codes"])
        self.assertTrue(result["daily_checkpoint"] == "verified")

    def test_ist_clock_resolves_to_correct_utc_period(self):
        guard = PortfolioEquityGuard(self.db)
        guard.observe("1000", at=utc(23, 0, 1))
        ist = timezone(timedelta(hours=5, minutes=30))
        result = self.check(utc(23, 0, 2).astimezone(ist))
        self.assertEqual(result["daily_checkpoint"], "verified")
        self.assertEqual(result["weekly_checkpoint"], "verified")

    def test_never_mutates_immutable_evidence(self):
        guard = PortfolioEquityGuard(self.db)
        guard.observe("1000", at=utc(23, 0, 1))
        before = self.db.read_bytes()
        self.check(utc(23, 0, 2))
        self.assertEqual(self.db.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
