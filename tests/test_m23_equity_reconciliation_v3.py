import unittest
from tradebot.m23_equity_reconciliation_v3 import compare

def p(kind,amount,id="1",at=150,asset="USD"):
    return dict(id=id,type=kind,amount=amount,at_us=at,asset=asset)

class ReconciliationTests(unittest.TestCase):
    def test_capital_outflow_not_loss(self):
        r=compare((100,"1000"),(200,"600"),[p("sub_account_transfer","-400")])
        self.assertTrue(r["raw_decline"])
        self.assertFalse(r["adjusted_decline"])
        self.assertTrue(r["residual_zero"])
        self.assertFalse(r["historical_account_binding_verified"])
        self.assertFalse(r["verified_return"])
    def test_remaining_loss(self):
        r=compare((100,"1000"),(200,"590"),[p("sub_account_transfer","-400")])
        self.assertTrue(r["adjusted_decline"])
        self.assertFalse(r["residual_zero"])
    def test_unclassified(self):
        r=compare((100,"1000"),(200,"600"),[p("unknown","-400")])
        self.assertEqual(r["status"],"unclassified_postings")
        self.assertNotIn("adjusted_decline",r)
    def test_no_double_count(self):
        row=p("sub_account_transfer","-400")
        r=compare((100,"1000"),(200,"600"),[row,row])
        self.assertEqual(r["counts"]["capital"],1)
    def test_wrong_boundary(self):
        with self.assertRaises(ValueError):
            compare((100,"1000"),(200,"600"),[p("sub_account_transfer","-400",at=100)])
    def test_conflicting_duplicate(self):
        with self.assertRaises(ValueError):
            compare((100,"1000"),(200,"600"),[p("sub_account_transfer","-400"),p("sub_account_transfer","-401")])
