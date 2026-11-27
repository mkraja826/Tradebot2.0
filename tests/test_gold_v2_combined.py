import unittest
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_combined import simulate,compare

C={"direction":"LONG","atr":1,"stop_distance_atr_hypothesis":2,
   "target_distance_atr_hypothesis":6,"entry_ema9":100}
def b(i,o,h,l,c):return Bar(i*300,o,h,l,c,1)

class CombinedTests(unittest.TestCase):
    def test_fixed_turnover_fees(self):
        x=simulate(C,[b(1,100,101,99,101)],as_of=0,horizon=1)
        self.assertAlmostEqual(x["gross_bps_initial_notional"],100)
        self.assertAlmostEqual(x["cost_bps_initial_notional"],15.075)
    def test_add_rejected_at_original_stop(self):
        bars=[b(1,100,100.8,99.5,100.6),b(2,100.6,101,100,100.8)]
        x=simulate(C,bars,as_of=0,horizon=2,policy="hybrid_scaling")
        self.assertEqual(x["adds"],0)
        self.assertEqual(x["rejected_adds"],1)
    def test_add_after_stop_tightens(self):
        bars=[b(1,100,102,99,101.5),b(2,101.5,102.5,101,102)]
        x=simulate(C,bars,as_of=0,horizon=2,policy="hybrid_scaling",cost_bps=0)
        self.assertEqual(x["adds"],1)
        self.assertEqual(x["peak_quantity_units"],2)
        self.assertAlmostEqual(x["gross_bps_initial_notional"],250)
    def test_partial_precedes_add_and_no_overclose(self):
        bars=[b(1,100,102,99,101.5),b(2,103,104,102,103.5)]
        x=simulate(C,bars,as_of=0,horizon=2,policy="hybrid_scaling",cost_bps=0)
        self.assertTrue(x["partial"])
        self.assertEqual(x["adds"],0)
        self.assertAlmostEqual(sum(e["units"] for e in x["events"] if e["action"] in ("partial","exit")),1)
    def test_gap_stop(self):
        bars=[b(1,100,102,99,101.5),b(2,97,98,96,97)]
        x=simulate(C,bars,as_of=0,horizon=2,policy="hybrid_scaling",cost_bps=0)
        self.assertEqual(x["reason"],"gap_stop")
        self.assertAlmostEqual(x["gross_bps_initial_notional"],-300)
    def test_ambiguous(self):
        x=simulate(C,[b(1,100,104,97,100)],as_of=0,horizon=1,policy="hybrid_exit")
        self.assertEqual(x["status"],"ambiguous_intrabar")
    def test_short_add_after_stop_tightens(self):
        bars=[b(1,100,101,98,98.5),b(2,98.5,99,97.5,98)]
        x=simulate(dict(C,direction="SHORT"),bars,as_of=0,horizon=2,policy="hybrid_scaling",cost_bps=0)
        self.assertEqual(x["adds"],1)
        self.assertAlmostEqual(x["gross_bps_initial_notional"],250)
    def test_reduce_next_open(self):
        bars=[b(1,100,100.2,99.2,99.3),b(2,99,99.4,98.5,98.5)]
        x=simulate(C,bars,as_of=0,horizon=2,policy="hybrid_scaling",cost_bps=0)
        self.assertTrue(x["reduced"])
        self.assertAlmostEqual(x["gross_bps_initial_notional"],-125)
    def test_compare(self):
        x=compare(C,[b(1,100,101,99,100)],as_of=0,horizon=1)
        self.assertEqual(len(x["results"]),3)
        self.assertEqual(x["execution_effect"],"none")
