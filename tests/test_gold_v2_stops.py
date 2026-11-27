import unittest
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_stops import simulate,compare

C={"direction":"LONG","atr":1,"stop_distance_atr_hypothesis":2,
   "target_distance_atr_hypothesis":6,"entry_ema9":100}
def b(i,o,h,l,c):return Bar(i*300,o,h,l,c,1)
class StopsTests(unittest.TestCase):
    def test_fixed_baseline(self):
        x=simulate(C,[b(1,100,101,99,101)],as_of=0,horizon=1)
        self.assertAlmostEqual(x["net_bps"],85)
    def test_no_same_bar_retroactive_stop(self):
        bars=[b(1,100,102,98.5,101.5),b(2,101.5,102,101,101.8)]
        x=simulate(C,bars,as_of=0,horizon=2,policy="hybrid")
        self.assertEqual(x["reason"],"horizon")
        self.assertEqual(x["stop_changes"][0]["effective_from"],300)
    def test_long_ratchet(self):
        bars=[b(1,100,102,99,101.5),b(2,101.5,103,101,102.5),b(3,102.5,103,102,102.7)]
        x=simulate(C,bars,as_of=0,horizon=3,policy="hybrid")
        self.assertTrue(x["stop_changes"])
        self.assertTrue(all(y["new"]>y["old"] for y in x["stop_changes"]))
    def test_short_ratchet(self):
        bars=[b(1,100,101,98,98.5),b(2,98.5,99,97,97.5),b(3,97.5,98,97,97.3)]
        x=simulate(dict(C,direction="SHORT"),bars,as_of=0,horizon=3,policy="hybrid")
        self.assertTrue(x["stop_changes"])
        self.assertTrue(all(y["new"]<y["old"] for y in x["stop_changes"]))
    def test_gap_through_stop(self):
        bars=[b(1,100,102,99,101.5),b(2,99,100,98,99)]
        x=simulate(C,bars,as_of=0,horizon=2,policy="hybrid")
        self.assertEqual(x["reason"],"gap_stop")
        self.assertEqual(x["exit_reference"],99)
    def test_missing_ema(self):
        c=dict(C);c.pop("entry_ema9")
        self.assertEqual(simulate(c,[b(1,100,101,99,100)],as_of=0,horizon=1,policy="ema9_trail")["status"],"missing_ema_seed")
    def test_ambiguous_bar(self):
        self.assertEqual(simulate(C,[b(1,100,107,97,100)],as_of=0,horizon=1)["status"],"ambiguous_intrabar")
    def test_compare(self):
        x=compare(C,[b(1,100,101,99,100)],as_of=0,horizon=1)
        self.assertEqual(len(x["results"]),5)
        self.assertEqual(x["execution_effect"],"none")
