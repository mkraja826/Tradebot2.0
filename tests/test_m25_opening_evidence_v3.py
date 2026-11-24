import unittest
from decimal import Decimal
from tradebot.m25_opening_evidence_v3 import compare

def posting(i,amount,kind="sub_account_transfer",**kw):
    return dict(id=str(i),amount=amount,type=kind,asset="USD",product_id=None,at_us=150)|kw

class OpeningTests(unittest.TestCase):
    def test_exact_cashflow_match_is_conditional(self):
        r=compare(100,200,Decimal("100"),[posting(1,"100")],84)
        self.assertTrue(r["conditional_cashflow_matches_first_equity"])
        self.assertFalse(r["inception_equity_verified"])
        self.assertFalse(r["risk_anchor_created"])
    def test_difference(self):
        self.assertFalse(compare(100,200,Decimal("99"),[posting(1,"100")],84)["conditional_cashflow_matches_first_equity"])
    def test_duplicate(self):
        p=posting(1,"100")
        r=compare(100,200,Decimal("100"),[p,p],84)
        self.assertEqual(r["posting_count"],1)
    def test_unknown_currency_product_or_type(self):
        for p in (posting(1,"100",asset="EUR"),posting(1,"100",product_id="181689"),posting(1,"100",kind="unknown")):
            r=compare(100,200,Decimal("100"),[p],84)
            self.assertIsNone(r["conditional_cashflow_matches_first_equity"])
    def test_outside_window(self):
        with self.assertRaises(ValueError):
            compare(100,200,Decimal("100"),[posting(1,"100",at_us=201)],84)
    def test_conflict(self):
        with self.assertRaises(ValueError):
            compare(100,200,Decimal("100"),[posting(1,"100"),posting(1,"101")],84)

class DiscrepancyTests(unittest.TestCase):
    def test_credit_and_residual(self):
        from tradebot.m25_opening_evidence_v3 import discrepancy
        r=discrepancy(100,200,Decimal("101"),[posting(1,"100",kind="external_deposit")],84,[])
        self.assertTrue(r["initial_credit_present"])
        self.assertEqual(r["discrepancy_class"],"one_cent_or_more")
        self.assertTrue(r["first_equity_above_net_postings"])
        self.assertFalse(r["accounting_explanation_verified"])
    def test_subcent_not_cleared(self):
        from tradebot.m25_opening_evidence_v3 import discrepancy
        r=discrepancy(100,200,Decimal("100.001"),[posting(1,"100")],84,[])
        self.assertEqual(r["discrepancy_class"],"sub_cent")
        self.assertFalse(r["precision_explains_difference"])
    def test_unknown_remains_unknown(self):
        from tradebot.m25_opening_evidence_v3 import discrepancy
        r=discrepancy(100,200,Decimal("100"),[posting(1,"100",asset="EUR")],84,[])
        self.assertEqual(r["discrepancy_class"],"unclassified")
        self.assertFalse(r["accounting_explanation_verified"])

class WalletChainTests(unittest.TestCase):
    def test_consistent_with_preexisting_balance(self):
        from unittest.mock import patch
        from tradebot.m25_opening_evidence_v3 import wallet_chain
        rows=[posting(1,"100",balance="110"),posting(2,"20",at_us=160,balance="130")]
        with patch("tradebot.m25_opening_evidence_v3.normalize_posting",side_effect=lambda x:x):
            r=wallet_chain(rows,Decimal("130"),100,200)
        self.assertEqual(r["balance_chain_status"],"consistent")
        self.assertTrue(r["implied_pre_first_posting_wallet_positive"])
        self.assertTrue(r["last_posting_wallet_matches_first_equity"])
        self.assertFalse(r["historical_net_equity_verified"])
    def test_inconsistent_chain(self):
        from unittest.mock import patch
        from tradebot.m25_opening_evidence_v3 import wallet_chain
        rows=[posting(1,"100",balance="110"),posting(2,"20",at_us=160,balance="131")]
        with patch("tradebot.m25_opening_evidence_v3.normalize_posting",side_effect=lambda x:x):
            r=wallet_chain(rows,Decimal("131"),100,200)
        self.assertEqual(r["balance_chain_status"],"inconsistent")
        self.assertFalse(r["historical_net_equity_verified"])
    def test_ambiguous_order(self):
        from unittest.mock import patch
        from tradebot.m25_opening_evidence_v3 import wallet_chain
        rows=[posting(1,"100",balance="110"),posting(2,"20",balance="130")]
        with patch("tradebot.m25_opening_evidence_v3.normalize_posting",side_effect=lambda x:x):
            r=wallet_chain(rows,Decimal("130"),100,200)
        self.assertEqual(r["balance_chain_status"],"ambiguous_order")
