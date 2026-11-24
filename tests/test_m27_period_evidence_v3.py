import unittest
from tradebot.m27_period_evidence_v3 import period
S=1000000000
U=1000000
class PeriodEvidenceTests(unittest.TestCase):
    def test_new_account(self):
        r=period(S,S+900*U,S+500*U,S+400*U,[S+500*U])
        self.assertEqual(r["state"],"account_created_after_window")
        self.assertFalse(r["risk_anchor_created"])
    def test_boundaries(self):
        for offset,state in ((299,"receipt_observed_in_window"),(300,"opening_unobserved")):
            t=S+offset*U
            r=period(S,S+900*U,t,S-U,[t])
            self.assertEqual(r["state"],state)
    def test_pending(self):
        self.assertEqual(period(S,S+30*U,S-U,S-2*U,[S-U])["state"],"window_pending")
    def test_missing(self):
        self.assertEqual(period(S,S+900*U,S-U,S-2*U,[S-U,S+500*U])["state"],"opening_receipt_missing")
    def test_invalid(self):
        with self.assertRaises(ValueError):period(S,S+U,S,S+U,[S])
