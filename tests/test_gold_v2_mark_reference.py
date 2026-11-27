import unittest
from recover_trading.gold_v2_mark_reference import research,collect_mark
from recover_trading.gold_v2_entry_adapter import select

NOW=3600020
def reader(params):
    assert params["symbol"]=="MARK:XAUTUSD"
    step={"5m":300,"15m":900,"1h":3600}[params["resolution"]]
    return [{"time":t,"open":100+i*.01,"high":101+i*.01,"low":99+i*.01,"close":100.1+i*.01}
            for i,t in enumerate(range(params["start"],params["end"],step))]
class MarkTests(unittest.TestCase):
    def test_mark_without_traded_volume(self):
        x=research(reader,NOW,source="production_mark")
        self.assertEqual(x["status"],"observed")
        self.assertFalse(x["report"]["execution_eligible"])
        self.assertIsNone(x["report"]["features"][300]["rolling_vwap20"])
        self.assertIsNone(x["report"]["features"][300]["relative_volume20"])
        self.assertEqual(select(x["report"]),(None,"reference_research_only"))
    def test_anomalies_preserved(self):
        def spike(p):
            rows=reader(p);rows[100]["high"]+=100
            return rows
        x=research(spike,NOW,source="demo_mark")
        self.assertEqual(x["status"],"data_unusable")
        self.assertEqual(x["candidate_count"],0)
        self.assertEqual(x["feed_health"]["5m"]["true_range_anomalies"],1)
    def test_missing_candle(self):
        x=research(lambda p:reader(p)[1:],NOW,source="production_mark")
        self.assertEqual(x["status"],"data_unusable")
        self.assertEqual(x["feed_health"]["1h"]["status"],"unavailable")
