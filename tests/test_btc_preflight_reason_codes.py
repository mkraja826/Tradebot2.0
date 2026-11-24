"""Exact pre-order failure codes are audit evidence, never order permission."""
import unittest
from tradebot.fire_execution import (
    FireTradeError, safe_exchange_preflight_detail, EXCHANGE_PREFLIGHT_LABELS,
)
from tradebot.fire_risk import RiskRejected


class PreflightRejectionCodeTests(unittest.TestCase):
    def test_all_documented_preflight_failures_are_classified(self):
        for raw,label in EXCHANGE_PREFLIGHT_LABELS.items():
            with self.subTest(label=label):
                self.assertEqual(safe_exchange_preflight_detail(FireTradeError(raw)),label)

    def test_unknown_error_does_not_leak_raw_data(self):
        self.assertEqual(safe_exchange_preflight_detail(
            FireTradeError("account private token 12345")),
            "unclassified_exchange_preflight_failure")
        self.assertEqual(safe_exchange_preflight_detail(
            RuntimeError("secret session response")),
            "exchange_preflight_exception_unclassified")

    def test_risk_rejection_gets_existing_safe_label(self):
        self.assertEqual(safe_exchange_preflight_detail(
            RiskRejected("Invalid stop or target against executable quote")),
            "stop_target_quote_invalid")
