import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from recover_trading.gold_v2_hybrid_validation import HybridJournal
from test_gold_v2_hybrid_validation import B,packet,ticker

class HybridIntegrityTests(unittest.TestCase):
    def test_enrollment_microseconds(self):
        with TemporaryDirectory() as d:
            clock=[B+20.5]
            j=HybridJournal(Path(d)/"hybrid.sqlite",clock=lambda:clock[0])
            try:
                self.assertEqual(j.enroll(packet(B+20),as_of=B+20),"enrolled")
                self.assertEqual(j.db.execute("SELECT enrolled_us FROM hybrid_windows").fetchone()[0],(B+20)*1000000+500000)
                clock[0]=B+3620
                self.assertEqual(j.resolve(),0)
                clock[0]+=.5
                self.assertEqual(j.resolve(),1)
            finally:j.close()
    def test_quote_binding(self):
        with TemporaryDirectory() as d:
            t=B+20;j=HybridJournal(Path(d)/"hybrid.sqlite",clock=lambda:t)
            try:
                p=packet(t);p["version"]="gold-v2-hybrid.3"
                p["quotes"].update(demo_product_id=42,demo_best_bid="100",demo_best_ask="100",demo_mark_price="100")
                with self.assertRaisesRegex(ValueError,"unbound_entry_quote"):j.enroll(p,as_of=t)
                j.record_quote(ticker(t),42)
                p["quotes"]["demo_best_bid"]="99"
                with self.assertRaisesRegex(ValueError,"entry_quote_mismatch"):j.enroll(p,as_of=t)
                p["quotes"]["demo_best_bid"]="100"
                self.assertEqual(j.enroll(p,as_of=t),"enrolled")
            finally:j.close()
    def test_reopen_preserves_microseconds(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"hybrid.sqlite";t=B+20.25
            j=HybridJournal(p,clock=lambda:t);j.enroll(packet(B+20),as_of=B+20);j.close()
            j=HybridJournal(p,clock=lambda:t)
            try:self.assertEqual(j.db.execute("SELECT enrolled_us FROM hybrid_windows").fetchone()[0],(B+20)*1000000+250000)
            finally:j.close()
