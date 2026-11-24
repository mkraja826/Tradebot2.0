import unittest
from tradebot.m33_coverage_v3 import audit_windows

def w(a,b,t,*rows):
    return dict(start=a,end=b,observed=t,product_id=84,postings=list(rows))
def p(**kw):
    return dict(dict(id="x",at_us=15,asset="USD",type="sub_account_transfer",product_id=None,amount="10"),**kw)
class CoverageTests(unittest.TestCase):
    def test_overlap_and_trailing_gap(self):
        r=audit_windows([w(10,20,30),w(15,25,31)],10,30)
        self.assertEqual(r["uncovered_us"],5)
        self.assertFalse(r["query_intervals_cover_samples"])
        self.assertFalse(r["broker_finality_verified"])
    def test_internal_gap(self):
        r=audit_windows([w(10,20,30),w(25,35,40)],10,35)
        self.assertEqual((r["coverage_gaps"],r["uncovered_us"]),(1,5))
    def test_late_missing_and_revision(self):
        r=audit_windows([w(10,20,30),w(11,21,31,p()),w(12,22,32,p(amount="11")),w(13,23,33)],10,23)
        self.assertEqual(r["overlapping_query_late_ids"],1)
        self.assertEqual(r["overlapping_query_missing_ids"],1)
        self.assertEqual(r["conflicting_posting_ids"],1)
        self.assertEqual(r["capital_posting_ids"],1)
        self.assertFalse(r["execution_authorized"])
    def test_boundary_not_proof(self):
        r=audit_windows([w(10,20,30),w(15,25,31,p())],10,25)
        self.assertEqual(r["overlapping_query_late_ids"],0)
        self.assertTrue(r["query_intervals_cover_samples"])
        self.assertFalse(r["historical_loss_reconciled"])
    def test_regression_and_duplicate(self):
        with self.assertRaises(ValueError):audit_windows([w(11,20,30),w(10,21,31)],10,21)
        with self.assertRaises(ValueError):audit_windows([w(10,20,30,p(),p())],10,20)
