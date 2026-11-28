import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from recover_trading.gold_v2_hybrid_validation import HybridJournal
from recover_trading.gold_v2_hybrid import MARK_SOURCE
from recover_trading.gold_v2_fee_review import report
from test_gold_v2_hybrid_validation import packet,ticker

class FeeReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.p=Path(self.tmp.name)/"mark.sqlite"
        self.t=1795836020
        self.j=HybridJournal(self.p,clock=lambda:self.t,source=MARK_SOURCE)
        p=packet(self.t);p["signal_source"]=MARK_SOURCE;p["model_version"]="gold-v2-mark-model.2"
        p["hypotheses"][0]["translated_atr"]="2"
        self.j.enroll(p,as_of=self.t)
    def tearDown(self):
        self.j.close();self.tmp.cleanup()
    def resolve(self):
        for i in range(120):
            self.t+=30
            self.j.record_quote(ticker(self.t,106 if i>=10 else 100),42)
        self.assertEqual(self.j.resolve(),1)
    def test_pending_not_replayed(self):
        x=report(self.p,as_of=self.t)
        self.assertEqual(x["candidate_count"],0)
        self.assertEqual(x["exclusions"]["not_resolved_at_cutoff"],1)
    def test_reproduce_and_compare_without_writes(self):
        self.resolve()
        before=self.p.read_bytes()
        x=report(self.p,as_of=self.t)
        self.assertEqual(self.p.read_bytes(),before)
        self.assertEqual(x["candidate_count"],1)
        self.assertEqual(x["actual_fills"],0)
        r=x["results"][0]["scenarios"]
        self.assertEqual(set(r),{"2.13","5","15","30"})
        self.assertGreater(r["2.13"]["fixed"]["net_bps_initial_notional"],r["5"]["fixed"]["net_bps_initial_notional"])
    def test_missing_quote_excluded(self):
        self.resolve()
        with self.j.db:
            self.j.db.execute("DELETE FROM hybrid_quotes WHERE stamp=(SELECT min(stamp) FROM hybrid_quotes)")
        x=report(self.p,as_of=self.t)
        self.assertEqual(x["candidate_count"],0)
        self.assertEqual(x["exclusions"]["coverage_mismatch"],1)
    def test_wrong_cohort(self):
        other=Path(self.tmp.name)/"other.sqlite"
        j=HybridJournal(other);j.close()
        with self.assertRaisesRegex(ValueError,"wrong_study"):report(other,as_of=self.t)
