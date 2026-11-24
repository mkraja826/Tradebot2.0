import unittest
from test_execution_preview_v3 import ExecutionPreviewTests
from test_opportunity_scanner_v3 import NOW
from tradebot.decision_quality_v3 import assess,outcome
from tradebot.ai_replay_v3 import wait_fixture
class DecisionQualityTests(unittest.TestCase):
    def setUp(self):
        f=ExecutionPreviewTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.q,self.a,self.product=f.make(f.events[0]); self.short=f.make(f.events[1],"SHORT")
    def test_margin_and_identity(self):
        q,a,p=self.q,self.a,self.product
        x=assess(q,a,p,decision_at=NOW)
        self.assertAlmostEqual(x["proposal"]["notional_usd"],.3)
        self.assertAlmostEqual(x["proposal"]["simple_initial_margin_usd"],.15)
        self.assertAlmostEqual(x["proposal"]["margin_difference_usd"],.85)
        self.assertEqual(x["proposal"]["reward_risk_ratio"],1)
        self.assertFalse(x["proposal"]["broker_margin_verified"])
        self.assertIsNone(assess(q,a,dict(p,symbol="XAUTUSD"),decision_at=NOW)["proposal"]["notional_usd"])
        with self.assertRaises(ValueError): assess(dict(q,request_sha256="bad"),a,p,decision_at=NOW)
        self.assertIsNone(assess(q,wait_fixture(q),p,decision_at=NOW)["proposal"])
    def bars(self,s,start,end):
        return [dict(time=t,open=100,high=106,low=94,close=101,volume=10) for t in range(start,end,300)]
    def test_market_scenarios(self):
        for q,a in ((self.q,self.a),self.short[:2]):
            x=outcome(q,a,self.bars,decision_at=NOW,now=NOW+1200)
            self.assertEqual(x["exit_reason"],"stop")
            self.assertTrue(x["ambiguous_bar_stop_first"])
            self.assertAlmostEqual(x["gross_pct"],-5)
            self.assertAlmostEqual(x["cost_scenarios_pct"]["10"],-5.1)
            self.assertFalse(x["actual_fill_verified"])
        self.assertEqual(outcome(self.q,self.a,self.bars,decision_at=NOW,now=NOW)["status"],"pending")
        self.assertEqual(outcome(self.q,self.a,lambda *args:[],decision_at=NOW,now=NOW+1200)["status"],"missing_candles")
        self.a["plan"]["entry_type"]="LIMIT"
        self.assertEqual(outcome(self.q,self.a,self.bars,decision_at=NOW,now=NOW+1200)["status"],"limit_fill_not_modelled")
