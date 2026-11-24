import unittest
from tradebot.advanced_backtest_v3 import simulate,metrics,replay
class AdvancedBacktestTests(unittest.TestCase):
    def test_ambiguous_long_short(self):
        b=[dict(open=100,high=103,low=97,close=101)]
        for side in ("LONG","SHORT"):
            r=simulate(b,side,1)
            self.assertEqual(r["gross_return_pct"],-1)
            self.assertTrue(r["ambiguous_bar"])
            self.assertEqual(r["exit_reason"],"stop")
    def test_gap_and_target(self):
        b=[dict(open=100,high=100.5,low=99.5,close=100),dict(open=97,high=98,low=96,close=97)]
        self.assertEqual(simulate(b,"LONG",1)["gross_return_pct"],-3)
        self.assertEqual(simulate(b,"LONG",1)["exit_reason"],"stop_gap")
        self.assertEqual(simulate(b,"SHORT",1)["gross_return_pct"],2)
        self.assertEqual(simulate(b,"SHORT",1)["exit_reason"],"target_gap")
    def test_cost_and_invalid(self):
        r=metrics([simulate([dict(open=100,high=101,low=99,close=100.15)],"LONG")])
        self.assertEqual(r["cost_scenarios"]["5"]["positive"],1)
        self.assertEqual(r["cost_scenarios"]["20"]["positive"],0)
        with self.assertRaises(ValueError): simulate([dict(open=100,close=100)],"SHORT",0)
        with self.assertRaises(ValueError): replay("missing",start=1,end=300)
