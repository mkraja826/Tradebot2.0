import unittest
import tempfile
from pathlib import Path
from recover_trading.gold_v2_validation import Journal,HORIZON
from recover_trading.gold_v2_engine import Bar

NOW=3600000
def report(t=NOW):
    return {"symbol":"XAUTUSD","as_of":t,"status":"observed","version":"test",
            "candidates":[{"family":"trend_pullback","direction":"LONG","atr":1,
                           "stop_distance_atr_hypothesis":1,"target_distance_atr_hypothesis":2}],
            "intelligence":{"version":"test-score","candidates":[{"family":"trend_pullback",
                "direction":"LONG","support_index":1,"observed_groups":1}]}}

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.now=NOW
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"validation.sqlite"
        self.j=Journal(self.path,clock=lambda:self.now)
    def tearDown(self):
        self.j.close()
        self.tmp.cleanup()
    def bars(self):
        return [Bar(NOW+300*(i+2),100,103,99.5,102) for i in range(HORIZON)]
    def test_next_full_boundary(self):
        self.now=NOW+20
        x=self.j.enroll(report())
        self.assertEqual(x["entry_boundary"],NOW+300)
    def test_duplicate_and_persistence(self):
        self.j.enroll(report())
        self.j.close()
        self.j=Journal(self.path,clock=lambda:self.now)
        self.assertEqual(self.j.enroll(report())["status"],"duplicate")
        self.assertEqual(self.j.summary()["window_counts"],{"enrolled":1})
    def test_overlap(self):
        self.j.enroll(report())
        self.now+=300
        self.assertEqual(self.j.enroll(report(self.now))["status"],"overlap_excluded")
    def test_nonprospective(self):
        self.now+=300
        with self.assertRaises(ValueError):
            self.j.enroll(report())
    def test_no_candidate(self):
        self.assertEqual(self.j.enroll(dict(report(),candidates=[]))["status"],"no_candidate")
    def test_costs_and_once_only(self):
        self.j.enroll(report())
        self.now=NOW+300*(HORIZON+1)
        self.assertEqual(self.j.resolve(self.bars()),1)
        self.assertEqual(self.j.resolve(self.bars()),0)
        summary=self.j.summary()
        self.assertEqual(summary["observed_nonoverlapping_windows"],1)
        self.assertEqual(len(summary["groups"]),3)
        for g in summary["groups"]:
            self.assertAlmostEqual(g["mean_net_bps"],200-g["cost_bps"])
    def test_missing_window(self):
        self.j.enroll(report())
        self.now=NOW+300*(HORIZON+1)
        self.assertEqual(self.j.resolve([]),0)
        self.now+=86400
        self.assertEqual(self.j.resolve([]),1)
        self.assertEqual(self.j.summary()["exclusions"]["missing_window"],1)
    def test_wrong_symbol(self):
        with self.assertRaises(ValueError):
            self.j.enroll(dict(report(),symbol="BTCUSD"))
    def test_future_resolution(self):
        self.j.enroll(report())
        with self.assertRaises(ValueError):
            self.j.resolve(self.bars())
    def test_same_window_multiple_candidates_count_once(self):
        x=report()
        x["candidates"].append(dict(x["candidates"][0],family="liquidity_sweep"))
        self.j.enroll(x)
        self.now=NOW+300*(HORIZON+1)
        self.j.resolve(self.bars())
        self.assertEqual(self.j.summary()["observed_nonoverlapping_windows"],1)

    def test_paired_sizing_summary(self):
        self.j.enroll(report())
        self.now=NOW+300*(HORIZON+1)
        self.j.resolve(self.bars())
        stats=self.j.summary()["sizing_comparisons"]
        self.assertEqual(len(stats),9)
        self.assertTrue(all(x["paired_samples"]==1 for x in stats))
        self.assertTrue(all(x["mean_paired_difference_bps"]==0 for x in stats))

    def test_paired_stop_summary(self):
        x=report()
        x["features"]={300:{"ema":[100,100,100,100]}}
        self.j.enroll(x)
        self.now=NOW+300*(HORIZON+1)
        self.j.resolve(self.bars())
        stats=self.j.summary()["stop_comparisons"]
        self.assertEqual(len(stats),12)
        self.assertTrue(all(x["paired_samples"]==1 for x in stats))
        self.assertTrue(all(x["mean_paired_difference_bps"]==0 for x in stats))

    def test_paired_target_summary(self):
        self.j.enroll(report())
        self.now=NOW+300*(HORIZON+1)
        self.j.resolve(self.bars())
        stats=self.j.summary()["target_comparisons"]
        self.assertEqual(len(stats),12)
        self.assertTrue(all(x["paired_samples"]==1 for x in stats))
        for x in stats:
            expected=-50 if x["policy"] in ("partial","partial_and_giveback") else 0
            self.assertAlmostEqual(x["mean_paired_difference_bps"],expected)

    def test_paired_combined_summary(self):
        self.j.enroll(report())
        self.now=NOW+300*(HORIZON+1)
        self.j.resolve(self.bars())
        stats=self.j.summary()["combined_comparisons"]
        self.assertEqual(len(stats),6)
        self.assertTrue(all(x["paired_samples"]==1 for x in stats))
        for x in stats:
            self.assertAlmostEqual(x["mean_paired_difference_bps"],-50+0.0025*x["cost_bps"])
