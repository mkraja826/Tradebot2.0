import unittest,json
from pathlib import Path
from tempfile import TemporaryDirectory
from recover_trading.gold_v2_mark_context import annotate,VERSION
from recover_trading.gold_v2_hybrid import MARK_SOURCE
from recover_trading.gold_v2_hybrid_validation import HybridJournal
from test_gold_v2_hybrid_validation import packet,ticker,B

NOW=B+20
def evidence(alignment,stamp=NOW):
    return {"version":VERSION,"as_of":stamp,"intelligence":{"as_of":stamp,"candidates":[
        {"family":"trend_pullback","direction":"LONG","macro_alignment":alignment,
         "support_index":1,"observed_groups":2}]}}
def mark_packet():
    p=packet(NOW);p["signal_source"]=MARK_SOURCE;return p

class MarkContextTests(unittest.TestCase):
    def test_annotation_does_not_change_hypotheses(self):
        p=mark_packet()
        for alignment,group in ((1,"aligned"),(-1,"opposed"),(0,"neutral"),(None,"unknown")):
            x=annotate(p,evidence(alignment),now=NOW)
            self.assertEqual(x["hypotheses"],p["hypotheses"])
            self.assertEqual(x["macro_annotation"]["candidate_groups"][0]["macro_group"],group)
            self.assertFalse(x["execution_eligible"])
    def test_stale_and_future_context(self):
        for stamp in (NOW-121,NOW+1):
            x=annotate(mark_packet(),evidence(1,stamp),now=NOW)
            self.assertEqual(x["macro_annotation"]["status"],"unavailable")
            self.assertEqual(x["status"],"hypotheses_observed")
    def test_prospective_strata(self):
        clock=[NOW]
        with TemporaryDirectory() as t:
            j=HybridJournal(Path(t)/"mark.sqlite",clock=lambda:clock[0],source=MARK_SOURCE)
            try:
                x=annotate(mark_packet(),evidence(1),now=NOW)
                self.assertEqual(j.enroll(x,as_of=NOW),"enrolled")
                for i in range(120):
                    clock[0]+=30
                    j.record_quote(ticker(clock[0],106 if i>=10 else 100),42)
                self.assertEqual(j.resolve(),1)
                s=j.summary()
                self.assertEqual(s["macro_strata"][0]["macro_group"],"aligned")
                self.assertEqual(s["macro_strata"][0]["mean_sampled_net_bps"],585)
                self.assertEqual(s["actual_fills"],0)
            finally:j.close()
