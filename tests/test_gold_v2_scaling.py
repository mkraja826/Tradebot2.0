import unittest
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_scaling import simulate,compare

C={"direction":"LONG","atr":1,"stop_distance_atr_hypothesis":2,
   "target_distance_atr_hypothesis":4}
def bar(i,o,h,l,c):return Bar(i*300,o,h,l,c,1)
class ScalingTests(unittest.TestCase):
    def test_fixed_costs_per_fill(self):
        x=simulate(C,[bar(1,100,101,99,101)],as_of=0,horizon=1,cost_bps=15)
        self.assertAlmostEqual(x["gross_bps_initial_notional"],100)
        self.assertAlmostEqual(x["cost_bps_initial_notional"],15.075)
    def test_add_next_open(self):
        b=[bar(1,100,101,99.8,100.8),bar(2,101,102,100.8,102)]
        x=simulate(C,b,as_of=0,horizon=2,policy="add_winners",cost_bps=0)
        self.assertEqual(x["adds"],1)
        self.assertEqual(x["events"][1]["price"],101)
        self.assertEqual(x["peak_quantity_units"],2)
        self.assertAlmostEqual(x["gross_bps_initial_notional"],300)
    def test_reduce_next_open(self):
        b=[bar(1,100,100.2,99.2,99.3),bar(2,99,99.4,98.5,98.5)]
        x=simulate(C,b,as_of=0,horizon=2,policy="reduce_losers",cost_bps=0)
        self.assertTrue(x["reduced"])
        self.assertAlmostEqual(x["gross_bps_initial_notional"],-125)
    def test_bracket_precedes_resize(self):
        b=[bar(1,100,101,99.8,100.8),bar(2,104,105,103,105)]
        x=simulate(C,b,as_of=0,horizon=2,policy="add_winners",cost_bps=0)
        self.assertEqual(x["adds"],0)
        self.assertEqual(x["reason"],"gap_target_conservative")
    def test_ambiguous(self):
        self.assertEqual(simulate(C,[bar(1,100,105,97,100)],as_of=0,horizon=1)["status"],"ambiguous_intrabar")
    def test_short(self):
        b=[bar(1,100,100.2,99,99.2),bar(2,99,99.2,98,98)]
        x=simulate(dict(C,direction="SHORT"),b,as_of=0,horizon=2,policy="add_winners",cost_bps=0)
        self.assertAlmostEqual(x["gross_bps_initial_notional"],300)
    def test_cap(self):
        b=[bar(1,100,101,99.9,100.9)]
        for i in range(2,10):
            p=100+i*.8
            b.append(bar(i,p,p+.1,p-.1,p))
        x=simulate(dict(C,target_distance_atr_hypothesis=20),b,as_of=0,horizon=9,policy="add_winners")
        self.assertEqual(x["adds"],5)
        self.assertEqual(x["peak_quantity_units"],6)
    def test_compare(self):
        x=compare(C,[bar(1,100,101,99,100)],as_of=0,horizon=1)
        self.assertEqual(len(x["results"]),4)
        self.assertEqual(x["execution_effect"],"none")
