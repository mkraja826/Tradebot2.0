import unittest
from tradebot.provider_diagnostics_v3 import classify


class TransportDiagnosticsTests(unittest.TestCase):
    def test_transport_categories_are_static_and_sanitized(self):
        from tradebot.ai import PlanError
        from urllib.error import HTTPError, URLError
        cases=[(PlanError("Top Billing API HTTP 401"),"provider_authentication_or_permission"),
               (PlanError("Top Billing API HTTP 429"),"provider_rate_limited"),
               (PlanError("Top Billing API HTTP 503"),"provider_server_error"),
               (PlanError("Top Billing API HTTP 400"),"provider_request_rejected"),
               (PlanError("Top Billing API network error"),"provider_network_error"),
               (PlanError("Invalid Top Billing API JSON response"),"provider_malformed_response"),
               (TimeoutError("private fixture"),"provider_timeout"),
               (URLError(TimeoutError("private fixture")),"provider_timeout"),
               (HTTPError("https://example.invalid",403,"private fixture",None,None),"provider_authentication_or_permission"),
               (PlanError("private fixture"),"transport_outcome_unknown")]
        for exc,expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(classify(exc,"transport"),expected)


if __name__ == "__main__":
    unittest.main()
