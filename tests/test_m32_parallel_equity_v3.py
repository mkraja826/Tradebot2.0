import unittest
from tradebot.m32_parallel_equity_v3 import project

class ParallelTests(unittest.TestCase):
    def test_breach_preserved(self):
        old=dict(blocking_conditions=["equity_loss_limit_breached"])
        new=dict(status="observed_raw_declines_only",gaps_over_180s=0,sampled_archive_peak_decline="0")
        r=project(new,old)
        self.assertEqual(r["legacy_blocking_conditions"],old["blocking_conditions"])
        self.assertFalse(r["historical_equivalence_verified"])
        self.assertFalse(r["execution_authorized"])
        self.assertEqual(r["diagnostic_comparisons"]["daily"]["status"],"unresolved")
    def test_thresholds_inclusive(self):
        r=project(dict(status="observed_raw_declines_only",gaps_over_180s=0,daily_observed_decline="0.02",weekly_observed_decline="0.05",sampled_archive_peak_decline="0.08"),{})
        self.assertTrue(all(x["status"]=="observed_decline_at_or_above_reference" for x in r["diagnostic_comparisons"].values()))
    def test_gap_not_healthy(self):
        r=project(dict(status="observed_raw_declines_only",gaps_over_180s=1,sampled_archive_peak_decline="0"),{})
        self.assertEqual(r["diagnostic_comparisons"]["sampled_peak"]["status"],"unresolved")
    def test_unavailable(self):
        r=project({},{});self.assertEqual(r["candidate_status"],"unavailable")
        self.assertTrue(all(x["status"]=="unresolved" for x in r["diagnostic_comparisons"].values()))
