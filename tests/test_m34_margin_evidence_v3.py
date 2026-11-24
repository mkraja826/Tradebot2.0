import unittest
from tradebot.m34_margin_evidence_v3 import project
A=dict(status="signed_readonly_exposure_verified",identity_verified=True,flat_exposure_verified=True,execution_authorized=False,
       leverage_evidence=dict(status="signed_setting_observed",execution_authorized=False,configured_leverage="20",
                              blocked_order_margin_zero=True,within_existing_20x_ceiling=True))
class MarginEvidenceTests(unittest.TestCase):
    def test_zero_blocked_margin_is_not_quote(self):
        r=project(A)
        self.assertEqual(r["status"],"signed_existing_margin_setting_observed")
        for k in ("actual_order_margin_verified","broker_pretrade_quote_available","existing_blocked_margin_is_new_order_quote",
                  "account_maximum_leverage_verified","execution_authorized","order_mutation_permission_verified"):
            self.assertFalse(r[k])
    def test_missing_flatness(self):
        self.assertEqual(project(dict(A,flat_exposure_verified=False))["status"],"unresolved")
    def test_unverified_setting(self):
        self.assertEqual(project(dict(A,leverage_evidence={}))["status"],"unresolved")
