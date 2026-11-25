import unittest
from recover_trading.trailing_research import simulate

class TrailingTests(unittest.TestCase):
    def test_next_bar_only(self):
        rows=[{"open":100,"high":101.5,"low":99.5},{"open":101,"high":101.1,"low":100.2},{"open":101,"high":999,"low":1}]
        r=simulate(rows,"LONG",100,15,"trail_1atr")
        self.assertAlmostEqual(r["net_bps"],35)
        self.assertEqual(r["adjustments"],1)
    def test_short_symmetric(self):
        rows=[{"open":100,"high":100.5,"low":98.5},{"open":99,"high":99.8,"low":98.9},{"open":99,"high":999,"low":1}]
        r=simulate(rows,"SHORT",100,15,"trail_1atr")
        self.assertAlmostEqual(r["net_bps"],35)
    def test_gap_after_cost_offset(self):
        rows=[{"open":100,"high":101.2,"low":99.5},{"open":99.9,"high":100,"low":99.8}]
        r=simulate(rows,"LONG",100,15,"cost_offset")
        self.assertEqual(r["exit_reason"],"stop_gap")
        self.assertAlmostEqual(r["net_bps"],-25)
    def test_both_barriers(self):
        rows=[{"open":100,"high":104,"low":98},{"open":100,"high":100,"low":100}]
        a=simulate(rows,"LONG",100,15,"trail_1atr")
        b=simulate(rows,"LONG",100,15,"trail_1atr",ambiguous="target")
        self.assertTrue(a["ambiguous"])
        self.assertAlmostEqual(a["net_bps"],-115)
        self.assertAlmostEqual(b["net_bps"],285)
    def test_fixed_matches_reference(self):
        rows=[{"open":100,"high":100.2,"low":99.8},{"open":100.3,"high":999,"low":1}]
        r=simulate(rows,"LONG",100,15,"fixed_atr")
        self.assertAlmostEqual(r["net_bps"],15)
        self.assertEqual(r["adjustments"],0)
