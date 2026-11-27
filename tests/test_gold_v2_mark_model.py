import unittest
from recover_trading.gold_v2_engine import Bar
from recover_trading.gold_v2_mark_aggregation import aggregate
from recover_trading.gold_v2_mark_model import corroborate,evaluate_mark

NOW=3600000
def fine():
    b=[Bar(t,100,101,99,100,0) for t in range(NOW-750*300+300,NOW+1,300)]
    x=b[300];b[300]=Bar(x.ts,100,130,99,100,0)
    return b
def frame(sec):
    return [Bar(t,100,101,99,100,0) for t in range(NOW-250*sec+sec,NOW+1,sec)]
class MarkModelTests(unittest.TestCase):
    def test_shared_historical_range(self):
        f=fine();b=aggregate(f,900)
        x=corroborate(b,b,f,seconds=900,as_of=NOW)
        self.assertEqual(x["status"],"historical_volatility_corroborated")
        self.assertEqual(len(x["corroborated"]),1)
    def test_not_corroborated(self):
        f=fine();b=aggregate(f,900)
        x=corroborate(b,frame(900),f,seconds=900,as_of=NOW)
        self.assertEqual(x["status"],"historical_extreme_range_unverified")
        self.assertEqual(len(x["unverified"]),1)
    def test_aggregation_mismatch(self):
        f=fine();b=aggregate(f,900)
        x=corroborate(b,b,frame(300),seconds=900,as_of=NOW)
        self.assertEqual(x["status"],"historical_extreme_range_unverified")
    def test_latest_shock(self):
        f=fine();f[-1]=Bar(NOW,100,130,99,100,0);b=aggregate(f,900)
        self.assertEqual(corroborate(b,b,f,seconds=900,as_of=NOW)["status"],"current_true_range_unverified")
    def test_separate_research_model(self):
        f=fine();b=aggregate(f,900)
        x=evaluate_mark({300:frame(300),900:b,3600:frame(3600)},{900:b},f,NOW)
        self.assertEqual(x["status"],"observed")
        self.assertFalse(x["execution_eligible"])
        self.assertEqual(x["candidates"],[])
