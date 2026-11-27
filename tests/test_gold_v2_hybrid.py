import unittest
from recover_trading.gold_v2_hybrid import preview
from recover_trading.gold_v2_reference import SOURCE
NOW=3600020
def reference(side="LONG"):
    return {"symbol":"XAUTUSD","signal_source":SOURCE,"as_of":NOW-1,
            "strict_reference_report":{"symbol":"XAUTUSD","signal_source":SOURCE,"status":"observed",
              "as_of":NOW-1,"candidates":[{"family":"trend_pullback","direction":side,"atr":2,
              "reference_close":100,"stop_distance_atr_hypothesis":1.5,"target_distance_atr_hypothesis":3}]}}
def ticker(pid,price,stamp=NOW):
    return {"symbol":"XAUTUSD","product_id":pid,"timestamp":stamp*1000000,"mark_price":str(price),
            "quotes":{"best_bid":str(price),"best_ask":str(price)}}
def run(ref=None,r=None,d=None,**kw):
    args=dict(reference_pid=1,demo_pid=2,tick_size=".1",now=NOW);args.update(kw)
    return preview(reference() if ref is None else ref,ticker(1,100) if r is None else r,
                   ticker(2,110) if d is None else d,**args)
class HybridTests(unittest.TestCase):
    def test_long(self):
        x=run();self.assertEqual(x["status"],"hypotheses_observed")
        self.assertFalse(x["execution_eligible"])
        p=x["hypotheses"][0]
        self.assertEqual(float(p["translated_atr"]),2.2)
        self.assertEqual(float(p["hypothetical_stop"]),106.7)
        self.assertEqual(float(p["hypothetical_target"]),116.6)
        self.assertTrue(p["mark_geometry_compatible"])
        self.assertAlmostEqual(x["quotes"]["mark_basis_bps"],1000)
    def test_short(self):
        p=run(reference("SHORT"))["hypotheses"][0]
        self.assertEqual(float(p["hypothetical_stop"]),113.3)
        self.assertEqual(float(p["hypothetical_target"]),103.4)
    def test_stale_signal(self):
        self.assertEqual(run(now=NOW+121)["status"],"stale_signal")
    def test_stale_quote(self):
        self.assertEqual(run(d=ticker(2,110,NOW-31))["status"],"quote_unavailable")
    def test_quote_skew(self):
        self.assertEqual(run(d=ticker(2,110,NOW-6))["status"],"quote_pair_not_synchronous")
    def test_wrong_product(self):
        self.assertEqual(run(d=ticker(3,110))["status"],"quote_unavailable")
    def test_invalid_mark_geometry(self):
        d=ticker(2,110);d["mark_price"]="95"
        self.assertFalse(run(d=d)["hypotheses"][0]["mark_geometry_compatible"])
    def test_bad_reference(self):
        r=reference();r["strict_reference_report"]["status"]="data_unusable"
        self.assertEqual(run(ref=r)["status"],"reference_data_unusable")
    def test_no_candidate(self):
        r=reference();r["strict_reference_report"]["candidates"]=[]
        self.assertEqual(run(ref=r)["status"],"no_candidate")
