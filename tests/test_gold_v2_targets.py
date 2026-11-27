import unittest
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_targets import simulate,compare

C={"direction":"LONG","atr":1,"stop_distance_atr_hypothesis":2,
   "target_distance_atr_hypothesis":4}
def b(i,o,h,l,c):return Bar(i*300,o,h,l,c,1)
class TargetTests(unittest.TestCase):
    def test_fixed(self):
        x=simulate(C,[b(1,100,105,99,104)],as_of=0,horizon=1)
        self.assertAlmostEqual(x["net_bps"],385)
    def test_partial(self):
        x=simulate(C,[b(1,100,105,99,104)],as_of=0,horizon=1,policy="partial")
        self.assertAlmostEqual(x["gross_bps"],300)
        self.assertEqual([f["quantity_fraction"] for f in x["exit_fills"]],[.5,.5])
    def test_partial_then_stop(self):
        bars=[b(1,100,103,99,102.5),b(2,102,103,97,98)]
        x=simulate(C,bars,as_of=0,horizon=2,policy="partial")
        self.assertAlmostEqual(x["gross_bps"],0)
    def test_ambiguous_partial(self):
        x=simulate(C,[b(1,100,103,97,100)],as_of=0,horizon=1,policy="partial")
        self.assertEqual(x["status"],"ambiguous_intrabar")
    def test_extension(self):
        bars=[b(1,100,102,99,101.5),b(2,101.5,103,101,102.8),b(3,103,105.2,102,105)]
        x=simulate(C,bars,as_of=0,horizon=3,policy="trend_extension")
        self.assertAlmostEqual(x["gross_bps"],500)
        self.assertEqual(x["target_changes"][0]["effective_from"],600)
    def test_no_retroactive_extension(self):
        bars=[b(1,100,102,99,101.5),b(2,101.5,104.2,101,103.5),b(3,104,106,103,105)]
        x=simulate(C,bars,as_of=0,horizon=3,policy="trend_extension")
        self.assertAlmostEqual(x["gross_bps"],400)
        self.assertFalse(x["target_changes"])
    def test_giveback_next_open(self):
        bars=[b(1,100,102,99,101.8),b(2,101.8,102,100.5,100.8),b(3,100.5,101,100,100.7)]
        x=simulate(C,bars,as_of=0,horizon=3,policy="profit_giveback")
        self.assertEqual(x["reason"],"giveback_next_open")
        self.assertAlmostEqual(x["gross_bps"],50)
    def test_short_partial(self):
        x=simulate(dict(C,direction="SHORT"),[b(1,100,101,95,96)],as_of=0,horizon=1,policy="partial")
        self.assertAlmostEqual(x["gross_bps"],300)
    def test_gap_stop_precedes_pending(self):
        bars=[b(1,100,102,99,101.8),b(2,101.8,102,100.5,100.8),b(3,97,98,96,97)]
        x=simulate(C,bars,as_of=0,horizon=3,policy="profit_giveback")
        self.assertEqual(x["reason"],"gap_stop")
        self.assertAlmostEqual(x["gross_bps"],-300)
    def test_compare(self):
        x=compare(C,[b(1,100,101,99,100)],as_of=0,horizon=1)
        self.assertEqual(len(x["results"]),5)
        self.assertEqual(x["execution_effect"],"none")
