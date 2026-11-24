import unittest
from tradebot.regime_learning_v3 import classify,regime_statistics,advisory
from tradebot.signal_learning_v3 import evaluate_event
from tradebot.opportunity_journal_v3 import digest
from test_opportunity_scanner_v3 import sig,NOW

class RegimeTests(unittest.TestCase):
    def setup_context(self,side="LONG"):
        signal=sig(direction=side)
        context={"market":{"frames":{"5m":{"status":"ready","closed_at":NOW,"features":{
            "adx14":30,"ema20":110,"ema50":100,"plus_di14":30,"minus_di14":10,"atr14_percentile100":90,"rvol20":1.8}}}}}
        return context,signal
    def test_classifications(self):
        c,s=self.setup_context()
        self.assertEqual(classify(c,s),dict(trend="uptrend",volatility="high",volume="high",alignment="aligned"))
        self.assertEqual(classify(c,dict(s,direction="SHORT"))["alignment"],"countertrend")
        f=c["market"]["frames"]["5m"]; f["features"]["adx14"]=15
        self.assertEqual(classify(c,s)["trend"],"range")
        f["features"]["atr14_percentile100"]=float("nan")
        self.assertEqual(classify(c,s)["volatility"],"unknown")
        f["closed_at"]=NOW+300
        self.assertEqual(set(classify(c,s).values()),{"unknown"})
    def test_descriptive_sample_count(self):
        row=dict(rule_id="B01",frame="5m",direction="LONG",horizon_minutes=15,regime={"trend":"uptrend"},status="observed",directional_return_pct=2,reference_start=NOW,reference_end=NOW+900)
        r=regime_statistics([row]*40)
        self.assertEqual(r[0]["distinct_windows"],1)
        self.assertEqual(r[0]["evidence"],"insufficient_sample")
        a=advisory("BTCUSD",r,as_of=NOW)
        self.assertEqual(a["groups_with_30_windows"],0)
        self.assertFalse(a["strategy_eligibility_changed"])
        self.assertEqual(advisory("XAUTUSD",[],as_of=NOW)["model_if_enabled"],"DeepSeek")
