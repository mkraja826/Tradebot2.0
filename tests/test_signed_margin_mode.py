"""Offline signed account identity and margin-mode proof after profile deprecation."""
import unittest

from tradebot.delta import DEMO_API
from tradebot.signed_margin_mode import (
    MarginModeEvidenceError, signed_account_margin_mode,
)


class FakeBroker:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self):
        self.calls = []
        self.user = 501
        self.preference_response = {"result": {"user_id": self.user}}
        self.account_response = {"result": [
            {"id": 901, "margin_mode": "portfolio"},
            {"id": self.user, "margin_mode": "isolated"},
        ]}

    def _request(self, method, path, *, auth=False, params=None, payload=None):
        self.calls.append((method, path, auth, params, payload))
        if method != "GET" or auth is not True or params or payload:
            raise AssertionError("signed evidence made a mutation or unsigned GET")
        if path == "/v2/users/trading_preferences":
            return self.preference_response
        if path == "/v2/sub_accounts":
            return self.account_response
        raise AssertionError("Unsupported or deprecated account endpoint")


class SignedMarginEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.broker = FakeBroker()

    def test_two_signed_reads_match_exact_user_id(self):
        result = signed_account_margin_mode(self.broker)
        self.assertEqual(result, "isolated")
        self.assertEqual(self.broker.calls, [
            ("GET", "/v2/users/trading_preferences", True, None, None),
            ("GET", "/v2/sub_accounts", True, None, None),
        ])
        self.assertFalse(any("/v2/profile" in call[1] for call in self.broker.calls))

    def test_execution_client_may_obtain_get_only_postfill_margin_proof(self):
        self.broker.allow_orders = True
        self.assertEqual(signed_account_margin_mode(self.broker), "isolated")
        self.assertTrue(all(call[0] == "GET" for call in self.broker.calls))

    def test_main_empty_subaccounts_can_use_explicit_signed_preferences_mode(self):
        self.broker.preference_response = {
            "result": {"user_id": 501, "margin_mode": "isolated"}}
        self.broker.account_response = {"result": []}
        self.assertEqual(signed_account_margin_mode(self.broker), "isolated")
        self.assertEqual(len(self.broker.calls), 2)
        self.assertTrue(all(call[0] == "GET" and call[2] is True
                            for call in self.broker.calls))

    def test_main_empty_subaccounts_without_explicit_mode_still_blocks(self):
        self.broker.account_response = {"result": []}
        with self.assertRaisesRegex(
                MarginModeEvidenceError, "signed_account_identity_not_unique"):
            signed_account_margin_mode(self.broker)

    def test_direct_portfolio_or_cross_never_passes_as_isolated(self):
        for mode in ("portfolio", "cross"):
            with self.subTest(mode=mode):
                self.broker.preference_response = {
                    "result": {"user_id": 501, "margin_mode": mode}}
                self.broker.account_response = {"result": []}
                self.assertEqual(signed_account_margin_mode(self.broker), mode)

    def test_conflicting_signed_modes_rejected(self):
        self.broker.preference_response = {
            "result": {"user_id": 501, "margin_mode": "isolated"}}
        self.broker.account_response = {"result": [
            {"id": 501, "margin_mode": "portfolio"}]}
        with self.assertRaisesRegex(
                MarginModeEvidenceError, "signed_margin_mode_conflict"):
            signed_account_margin_mode(self.broker)

    def test_foreign_subaccounts_never_become_current_user_mode(self):
        self.broker.preference_response = {
            "result": {"user_id": 501, "margin_mode": "isolated"}}
        self.broker.account_response = {"result": [
            {"id": 999, "margin_mode": "portfolio"}]}
        self.assertEqual(signed_account_margin_mode(self.broker), "isolated")

    def test_invalid_explicit_preferences_mode_cannot_fall_back_to_subaccount(self):
        for value in ("ISOLATED", "", True, 3, [], {}):
            with self.subTest(value=value):
                self.broker.calls.clear()
                self.broker.preference_response = {
                    "result": {"user_id": 501, "margin_mode": value}}
                with self.assertRaisesRegex(
                        MarginModeEvidenceError, "signed_margin_mode_unverified"):
                    signed_account_margin_mode(self.broker)
                self.assertEqual(len(self.broker.calls), 1)

    def test_different_user_subaccount_cannot_supply_mode(self):
        self.broker.account_response = {"result": [
            {"id": 901, "margin_mode": "isolated"},
        ]}
        with self.assertRaisesRegex(
                MarginModeEvidenceError, "signed_account_identity_not_unique"):
            signed_account_margin_mode(self.broker)

    def test_ambiguous_duplicate_current_account_is_rejected(self):
        self.broker.account_response["result"].append(
            {"id": 501, "margin_mode": "portfolio"})
        with self.assertRaisesRegex(
                MarginModeEvidenceError, "signed_account_identity_not_unique"):
            signed_account_margin_mode(self.broker)

    def test_missing_or_invalid_preferences_untrusted(self):
        for response in (
            {}, {"result": None}, {"result": {}},
            {"result": {"user_id": True}},
            {"result": {"user_id": "0"}},
            {"result": {"user_id": "bad-private-id"}},
        ):
            self.broker.preference_response = response
            with self.subTest(response=response), self.assertRaises(MarginModeEvidenceError):
                signed_account_margin_mode(self.broker)

    def test_missing_or_unknown_account_mode_blocks(self):
        for mode in (None, "unknown", "ISOLATED", True, 1, {}):
            self.broker.account_response = {"result": [
                {"id": 501, "margin_mode": mode},
            ]}
            with self.subTest(mode=mode), self.assertRaisesRegex(
                    MarginModeEvidenceError, "signed_margin_mode_unverified"):
                signed_account_margin_mode(self.broker)

    def test_portfolio_and_cross_modes_not_reinterpreted_as_isolated(self):
        for mode in ("portfolio", "cross"):
            self.broker.account_response = {"result": [
                {"id": 501, "margin_mode": mode},
            ]}
            self.assertEqual(signed_account_margin_mode(self.broker), mode)

    def test_current_account_must_be_unique_and_all_rows_have_id(self):
        self.broker.account_response = {"result": [
            {"margin_mode": "isolated"}, {"id": 501, "margin_mode": "isolated"}
        ]}
        with self.assertRaisesRegex(
                MarginModeEvidenceError, "signed_subaccount_identity_unverified"):
            signed_account_margin_mode(self.broker)

    def test_non_demo_or_malformed_client_never_makes_a_signed_request(self):
        for host, enabled in (("https://api.delta.exchange", False),
                              (DEMO_API, None), (DEMO_API, 0)):
            self.broker.calls.clear()
            self.broker.base_url, self.broker.allow_orders = host, enabled
            with self.assertRaisesRegex(
                    MarginModeEvidenceError, "delta_demo_client_required"):
                signed_account_margin_mode(self.broker)
            self.assertEqual(self.broker.calls, [])


if __name__ == "__main__":
    unittest.main()
