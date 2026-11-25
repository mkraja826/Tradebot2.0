import unittest
from recover_trading.bracket_research import simulate,window

class BracketTests(unittest.TestCase):
    def test_both_touched_long_short(self):
        rows=[{"open":100,"high":102,"low":98},{"open":100,"high":100,"low":100}]
        for side in ("LONG","SHORT"):
            a=simulate(rows,side,40,60,15)
            b=simulate(rows,side,40,60,15,ambiguous="target")
            self.assertTrue(a["ambiguous"])
            self.assertAlmostEqual(a["net_bps"],-55)
            self.assertAlmostEqual(b["net_bps"],45)
    def test_gap_and_time_exit(self):
        rows=[{"open":100,"high":100.1,"low":99.9},{"open":99,"high":101,"low":98}]
        a=simulate(rows,"LONG",40,60,15)
        self.assertEqual(a["exit_reason"],"stop_gap")
        self.assertAlmostEqual(a["net_bps"],-115)
        rows[-1]["open"]=100.1
        a=simulate(rows,"LONG",40,60,15)
        self.assertEqual(a["exit_reason"],"time_exit")
        self.assertAlmostEqual(a["net_bps"],-5)
    def test_target_gap_no_improvement(self):
        rows=[{"open":100,"high":100.1,"low":99.9},{"open":98,"high":100,"low":97}]
        a=simulate(rows,"SHORT",40,60,15)
        self.assertEqual(a["exit_reason"],"target_gap")
        self.assertAlmostEqual(a["net_bps"],45)
    def test_missing_window(self):
        self.assertIsNone(window({},{"entry_at":1800000000,"exit_at":1800000300}))
