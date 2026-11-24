import unittest
from tradebot.m31_cashflow_evidence_v3 import compare
S="BTCUSD"
A=dict(symbol=S,account_binding="a"*64,observed_us=1000000,equity_usd="100")
B=dict(A,observed_us=3000000,equity_usd="90")
def posting(**kw):
    return dict(dict(id="1",at_us=2000000,product_id=None,asset="USD",
                     type="sub_account_transfer",amount="-10",order_id=None,fill_id=None),**kw)
class CashflowTests(unittest.TestCase):
    def test_no_postings(self):
        r=compare(S,A,B,[],84)
        self.assertEqual(r["posting_count"],0)
        self.assertTrue(r["raw_cashflow_comparison_available"])
        self.assertFalse(r["verified_return"])
        self.assertFalse(r["execution_authorized"])
    def test_transfer_not_verified_index(self):
        r=compare(S,A,B,[posting()],84)
        self.assertEqual(r["capital_posting_count"],1)
        self.assertFalse(r["transfer_adjusted_risk_index_available"])
        self.assertFalse(r["historical_loss_reconciled"])
    def test_unknown_and_boundary(self):
        for p in (posting(type="unknown"),posting(asset="BTC"),posting(product_id="999"),posting(at_us=A["observed_us"]),posting(at_us=B["observed_us"])):
            self.assertEqual(compare(S,A,B,[p],84)["status"],"unresolved_posting_evidence")
    def test_scope(self):
        with self.assertRaises(ValueError):compare(S,A,dict(B,account_binding="b"*64),[],84)
        with self.assertRaises(ValueError):compare(S,A,B,[posting(at_us=4000000)],84)
    def test_duplicate(self):
        self.assertEqual(compare(S,A,B,[posting(),posting()],84)["posting_count"],1)
