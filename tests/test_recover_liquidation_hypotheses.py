import unittest
from recover_trading.liquidation_hypotheses import evaluate
class HypothesisTests(unittest.TestCase):
    def fixture(self,mark="102",rate="-0.0001"):
        a={"symbol":"BTCUSDT","source_ms":1000000,"mark_usdt":"100","open_interest_btc_both_sides":"100"}
        b={**a,"source_ms":1300000,"mark_usdt":mark,"open_interest_btc_both_sides":"99","indicative_funding_fraction":rate}
        s={"status":"subscribed","subscribed_ms":999999,"heartbeat_ms":1300001,"ended_ms":None}
        return b,a,s
    def test_short_squeeze(self):
        b,a,s=self.fixture()
        r=evaluate(b,a,[(1200000,1200001,"SHORT","0.6"),(1250000,1250001,"SHORT","0.5")],s,1300002)
        self.assertEqual(r["rules"][0]["status"],"experimental_signal")
        self.assertEqual(r["rules"][1]["status"],"no_observed_side_events")
        self.assertEqual(r["execution_effect"],"none")
    def test_long_liquidation(self):
        b,a,s=self.fixture("98","0.0001")
        r=evaluate(b,a,[(1200000,1200001,"LONG","0.6"),(1250000,1250001,"LONG","0.5")],s,1300002)
        self.assertEqual(r["rules"][1]["status"],"experimental_signal")
    def test_missing_events_and_gap(self):
        b,a,s=self.fixture()
        self.assertEqual(evaluate(b,a,[],s,1300002)["status"],"no_observed_events")
        s["subscribed_ms"]=1000001
        self.assertEqual(evaluate(b,a,[],s,1300002)["status"],"insufficient_evidence")
        self.assertEqual(evaluate(b,None,[],s,1300002)["status"],"insufficient_evidence")
