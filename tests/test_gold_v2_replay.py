import unittest
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_replay import outcome

C={"direction":"LONG","atr":1,"stop_distance_atr_hypothesis":1,
   "target_distance_atr_hypothesis":2}
class ReplayTests(unittest.TestCase):
    def test_target_after_signal(self):
        x=outcome(C,[Bar(300,100,103,99.5,102)],as_of=0)
        self.assertEqual(x["reason"],"target")
        self.assertAlmostEqual(x["net_bps"],185)
    def test_ambiguous(self):
        self.assertEqual(outcome(C,[Bar(300,100,103,98,101)],as_of=0)["status"],
                         "ambiguous_intrabar")
    def test_pending(self):
        self.assertEqual(outcome(C,[Bar(300,100,101,99.5,100)],as_of=0)["status"],
                         "pending")
    def test_gap(self):
        self.assertEqual(outcome(C,[Bar(600,100,101,99.5,100)],as_of=0)["status"],"gap")
    def test_short(self):
        x=outcome(dict(C,direction="SHORT"),[Bar(300,100,100.5,97,98)],as_of=0)
        self.assertAlmostEqual(x["net_bps"],185)
