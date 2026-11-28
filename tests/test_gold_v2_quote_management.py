import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from recover_trading.gold_v2_quote_management import compare,simulate
from recover_trading.gold_v2_hybrid_validation import HybridJournal
from recover_trading.gold_v2_hybrid import MARK_SOURCE
from test_gold_v2_hybrid_validation import packet,ticker,B

def plan(side="LONG"):
    return {"direction":side,"family":"fixture","demo_book_entry_reference":"100","translated_atr":"2",
            "hypothetical_stop":"97" if side=="LONG" else "103",
            "hypothetical_target":"106" if side=="LONG" else "94","mark_geometry_compatible":True}
def samples(*prices):
    return [(i+1,{"mark_price":str(p),"best_bid":str(p),"best_ask":str(p)}) for i,p in enumerate(prices)]
class QuoteManagementTests(unittest.TestCase):
    def test_fixed_long_and_short(self):
        for side,path in (("LONG",[101,106]),("SHORT",[99,94])):
            x=simulate(plan(side),samples(*path),policy="fixed",cost_bps=15)
            self.assertEqual(x["reason"],"sampled_target")
            self.assertGreater(x["net_bps_initial_notional"],580)
            self.assertFalse(x["fill_verified"])
    def test_stop_never_loosens(self):
        x=simulate(plan(),samples(101,102,103,104,103,101),policy="adaptive_exit",cost_bps=15)
        levels=[float(e["level"]) for e in x["events"] if e["action"]=="stop_tighten"]
        self.assertTrue(levels)
        self.assertEqual(levels,sorted(set(levels)))
    def test_reduction_next_sample(self):
        x=simulate(plan(),samples(99,98.5,100),policy="adaptive_scaling",cost_bps=15)
        e=[e for e in x["events"] if e["action"]=="reduce"]
        self.assertEqual(e[0]["stamp"],2)
        self.assertEqual(e[0]["units"],"0.5")
        self.assertTrue(x["reduced"])
    def test_partial_next_sample(self):
        x=simulate(plan(),samples(103,104,105),policy="adaptive_exit",cost_bps=15)
        e=[e for e in x["events"] if e["action"]=="partial"]
        self.assertEqual(e[0]["stamp"],2)
        self.assertTrue(x["partial"])
    def test_cost_sensitivity(self):
        x=compare(plan(),samples(101,103,104,105,106))
        self.assertGreater(x["results"]["5"]["fixed"]["net_bps_initial_notional"],x["results"]["30"]["fixed"]["net_bps_initial_notional"])
        self.assertEqual(len(x["results"]),3)
    def test_journal_pairs_frozen_on_enrollment(self):
        clock=[B+20]
        with TemporaryDirectory() as t:
            j=HybridJournal(Path(t)/"mark.sqlite",clock=lambda:clock[0],source=MARK_SOURCE)
            try:
                p=packet(clock[0]);p["signal_source"]=MARK_SOURCE;p["hypotheses"][0]["translated_atr"]="2"
                self.assertEqual(j.enroll(p,as_of=clock[0]),"enrolled")
                for i in range(120):
                    clock[0]+=30;j.record_quote(ticker(clock[0],106 if i>=10 else 100),42)
                self.assertEqual(j.resolve(),1)
                pairs=j.summary()["management_pairs"]
                self.assertEqual(len(pairs),6)
                self.assertTrue(all(x["paired_samples"]==1 for x in pairs))
            finally:j.close()
