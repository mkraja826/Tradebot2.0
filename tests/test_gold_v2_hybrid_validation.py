import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from recover_trading.gold_v2_hybrid_validation import HybridJournal
from recover_trading.gold_v2_reference import SOURCE

B=3600000
def ticker(t,mark=100,pid=42):
    return {"symbol":"XAUTUSD","product_id":pid,"timestamp":t*1000000,"mark_price":str(mark),
            "quotes":{"best_bid":str(mark),"best_ask":str(mark)}}
def packet(t):
    return {"symbol":"XAUTUSD","signal_source":SOURCE,"execution_eligible":False,
        "status":"hypotheses_observed","quotes":{"reference_quote_timestamp_us":t*1000000,
        "demo_quote_timestamp_us":t*1000000},"hypotheses":[{"family":"trend_pullback",
        "direction":"LONG","demo_book_entry_reference":"100","hypothetical_stop":"97",
        "hypothetical_target":"106","mark_geometry_compatible":True}]}
class HybridValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.t=B+20
        self.j=HybridJournal(Path(self.tmp.name)/"hybrid.sqlite",clock=lambda:self.t)
    def tearDown(self):self.j.close();self.tmp.cleanup()
    def test_no_backfill(self):
        with self.assertRaises(ValueError):self.j.enroll(packet(self.t-300),as_of=self.t-300)
    def test_duplicate_and_overlap(self):
        self.assertEqual(self.j.enroll(packet(self.t),as_of=self.t),"enrolled")
        self.assertEqual(self.j.enroll(packet(self.t),as_of=self.t),"duplicate")
        self.t+=300
        self.assertEqual(self.j.enroll(packet(self.t),as_of=self.t),"overlap_excluded")
    def test_sparse_never_profit(self):
        self.j.enroll(packet(self.t),as_of=self.t)
        self.t+=3600;self.j.record_quote(ticker(self.t,110),42)
        self.assertEqual(self.j.resolve(),1)
        self.assertEqual(self.j.summary()["window_counts"],{"insufficient_quote_coverage":1})
    def test_sampled_target_not_fill(self):
        import json
        self.j.enroll(packet(self.t),as_of=self.t)
        for i in range(120):
            self.t+=30;self.j.record_quote(ticker(self.t,106 if i>=10 else 100),42)
        self.assertEqual(self.j.resolve(),1)
        self.assertEqual(self.j.resolve(),0)
        x=json.loads(self.j.db.execute("SELECT evidence FROM hybrid_outcomes").fetchone()[0])
        self.assertFalse(x["fill_verified"])
        self.assertEqual(x["results"][0]["exit_reason"],"sampled_target")
        self.assertEqual(x["results"][0]["sampled_net_bps"],585)
        self.assertEqual(self.j.summary()["actual_fills"],0)
    def test_product_binding(self):
        self.j.record_quote(ticker(self.t),42)
        with self.assertRaises(ValueError):self.j.record_quote(ticker(self.t,pid=43),43)
    def test_conflicting_quote(self):
        self.j.record_quote(ticker(self.t),42)
        self.assertEqual(self.j.record_quote(ticker(self.t),42),"duplicate")
        with self.assertRaises(ValueError):self.j.record_quote(ticker(self.t,101),42)
