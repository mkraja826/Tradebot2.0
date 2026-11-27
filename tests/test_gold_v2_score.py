import unittest
from recover_trading.gold_v2_score import score

NOW=1795867200
def report(side="LONG"):
    return {"symbol":"XAUTUSD","status":"observed","as_of":NOW,
            "features":{s:{"direction":1} for s in (300,900,3600)},
            "candidates":[{"family":"trend_pullback","direction":side}],
            "fundamentals":{"as_of":NOW,"macro":{"broad_dollar_5obs_pct":-0.5,
                                                   "real_yield_5obs_bp":-10}}}

class ScoreTests(unittest.TestCase):
    def test_alignment(self):
        c=score(report())["candidates"][0]
        self.assertEqual((c["support_index"],c["observed_groups"]),(2,2))
    def test_short_opposed(self):
        self.assertEqual(score(report("SHORT"))["candidates"][0]["support_index"],-2)
    def test_missing_not_neutral(self):
        x=report(); x.pop("fundamentals")
        c=score(x)["candidates"][0]
        self.assertEqual(c["observed_groups"],1)
        self.assertIsNone(c["macro_alignment"])
    def test_stale_packet(self):
        x=report();x["fundamentals"]["as_of"]=NOW-1
        self.assertIsNone(score(x)["macro"]["direction"])
    def test_neutral_observed(self):
        x=report();x["fundamentals"]["macro"]={"broad_dollar_5obs_pct":0,
                                                   "real_yield_5obs_bp":0}
        c=score(x)["candidates"][0]
        self.assertEqual((c["macro_alignment"],c["observed_groups"]),(0,2))
    def test_annotations_do_not_vote(self):
        x=report();x["public_feeds"]={"as_of":NOW,"feeds":{"cot":{"status":"observed",
            "data":{"managed_money_net_change":10000}}}}
        y=score(x)
        self.assertFalse(y["positioning"]["vote_used"])
        self.assertEqual(y["candidates"][0]["support_index"],2)
    def test_unusable(self):
        x=report();x["status"]="data_unusable"
        self.assertEqual(score(x)["candidates"],[])
    def test_json_frame_keys(self):
        x=report();x["features"]={str(k):v for k,v in x["features"].items()}
        self.assertEqual(score(x)["technical"]["direction"],1)
    def test_wrong_market(self):
        x=report();x["symbol"]="BTCUSD"
        with self.assertRaises(ValueError):score(x)
