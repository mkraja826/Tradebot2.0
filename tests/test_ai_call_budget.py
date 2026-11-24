"""The paid AI call quota is durable across scheduler/service restarts."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from tradebot.ai_call_budget import AICallQuota


class QuotaTests(unittest.TestCase):
    def test_restarts_daily_and_monthly_budget_without_replaying_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "usage.sqlite"
            at = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)
            a = AICallQuota(ledger, daily_limit=2, monthly_limit=3)
            self.assertTrue(a.claim("tb-deepseek-v4-1-flash", at, "id1"))
            self.assertFalse(a.claim("tb-deepseek-v4-1-flash", at, "id1"))
            b = AICallQuota(ledger, daily_limit=2, monthly_limit=3)
            self.assertTrue(b.claim("tb-deepseek-v4-1-flash", at, "id2"))
            self.assertFalse(b.claim("tb-deepseek-v4-1-flash", at, "id3"))
            next_day = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
            self.assertTrue(b.claim("tb-deepseek-v4-1-flash", next_day, "id4"))
            self.assertFalse(b.claim("tb-deepseek-v4-1-flash", next_day, "id5"))
            self.assertTrue(b.claim("tb-gpt-6", next_day, "independent-model"))

    def test_timezone_aware_timestamps_required(self):
        with tempfile.TemporaryDirectory() as folder:
            budget = AICallQuota(Path(folder) / "usage.sqlite")
            with self.assertRaises(ValueError):
                budget.claim("tb-deepseek-v4-1-flash", datetime(2026, 11, 19), "x")


if __name__ == "__main__":
    unittest.main()
