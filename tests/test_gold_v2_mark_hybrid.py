import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from recover_trading.gold_v2_hybrid import preview_mark,preview,MARK_SOURCE
from recover_trading.gold_v2_hybrid_validation import HybridJournal
from recover_trading.gold_v2_reference import SOURCE
from test_gold_v2_hybrid import reference,ticker,NOW
from test_gold_v2_hybrid_validation import packet,B

class MarkHybridTests(unittest.TestCase):
    def test_mark_preview_preserves_provenance(self):
        r=reference();report=r.pop("strict_reference_report")
        r.update(signal_source=MARK_SOURCE,mark_report=report)
        report.update(signal_source=MARK_SOURCE,version="gold-v2-mark-model.1",execution_eligible=False)
        kw=dict(reference_pid=1,demo_pid=2,tick_size=".1",now=NOW)
        x=preview_mark(r,ticker(1,100),ticker(2,110),**kw)
        self.assertEqual(x["status"],"hypotheses_observed")
        self.assertEqual(x["signal_source"],MARK_SOURCE)
        self.assertFalse(x["execution_eligible"])
        self.assertEqual(preview(r,ticker(1,100),ticker(2,110),**kw)["status"],"wrong_reference")
    def test_journal_source_binding(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"mark.sqlite"
            j=HybridJournal(p,clock=lambda:B+20,source=MARK_SOURCE)
            try:
                x=packet(B+20)
                with self.assertRaisesRegex(ValueError,"wrong_study"):j.enroll(x,as_of=B+20)
                x["signal_source"]=MARK_SOURCE
                self.assertEqual(j.enroll(x,as_of=B+20),"enrolled")
            finally:j.close()
            with self.assertRaisesRegex(ValueError,"study_source_mismatch"):HybridJournal(p,source=SOURCE)
    def test_original_journal_rejects_mark(self):
        with TemporaryDirectory() as d:
            j=HybridJournal(Path(d)/"original.sqlite",clock=lambda:B+20)
            try:
                x=packet(B+20);x["signal_source"]=MARK_SOURCE
                with self.assertRaisesRegex(ValueError,"wrong_study"):j.enroll(x,as_of=B+20)
            finally:j.close()
