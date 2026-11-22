"""Offline tests: exposure evidence remains possible with empty subaccount list."""
import json
import unittest

from tradebot.delta import DeltaDemo
from tradebot.fire_exposure_only_probe import observe_exposure_without_margin


class ReadOnlyFake(DeltaDemo):
    def __init__(self):
        super().__init__(api_key="PRIVATE_TEST_KEY", api_secret="PRIVATE_SECRET",
                         allow_orders=False)
        self.calls = []
        self.margined = []
        self.live = {27: "0", 82: "0"}
        self.orders = []
        self.orders_cursor = None
        self.margin_meta = None
        self.invalid_path = None

    def _request(self, method, path, *, auth=False, params=None, payload=None):
        assert method == "GET" and auth is True and payload is None
        self.calls.append((path, params))
        if path == self.invalid_path:
            raise RuntimeError("SENSITIVE_PROVIDER_PRIVATE_BODY")
        if path == "/v2/sub_accounts":
            raise AssertionError("Subaccount endpoint should not be requested")
        if path == "/v2/users/trading_preferences":
            raise AssertionError("No account margin inference")
        if path == "/v2/positions/margined":
            return {"result": self.margined, "meta": self.margin_meta}
        if path == "/v2/orders":
            assert params["states"] == "open,pending"
            assert params["page_size"] == 50
            return {"result": self.orders, "meta": {"after": self.orders_cursor}}
        if path.startswith("/v2/products/"):
            symbol = path.rsplit("/", 1)[1]
            assert symbol in ("BTCUSD", "XAUTUSD")
            return {"result": {
                "id": 27 if symbol == "BTCUSD" else 82,
                "symbol": symbol, "contract_type": "perpetual_futures",
            }}
        if path == "/v2/positions":
            pid = params["product_id"]
            assert pid in (27, 82)
            return {"result": {"product_id": pid, "size": self.live[pid]}}
        raise AssertionError("Unrecognized broker endpoint")


class ExposureOnlyTests(unittest.TestCase):
    def setUp(self):
        self.ex = ReadOnlyFake()

    def test_empty_parent_listing_does_not_block_separate_exposure_sample(self):
        report = observe_exposure_without_margin(self.ex)
        self.assertEqual(report["status"], "signed_exposure_snapshot_observed")
        self.assertEqual(report["account_wide_margined_positions_nonzero"], 0)
        self.assertEqual(report["account_wide_open_or_pending_orders"], 0)
        self.assertEqual(report["realtime_fire_position_sizes"],
                         {"BTCUSD": "0", "XAUTUSD": "0"})
        self.assertTrue(report["margined_realtime_consistent"])
        self.assertFalse(report["any_exposure_observed"])
        for field in ("margin_mode_verified", "two_sweep_flatness_verified",
                      "full_financial_reconciliation_verified", "safe_to_deploy",
                      "safe_to_enable_fire", "trade_authorized",
                      "broker_order_mutations", "service_mutations"):
            self.assertIs(report[field], False)
        self.assertFalse(any("sub_accounts" in path for path, _ in self.ex.calls))
        self.assertFalse(any("trading_preferences" in path for path, _ in self.ex.calls))
        self.assertNotIn("PRIVATE", json.dumps(report))

    def test_position_on_other_product_cannot_be_missed(self):
        self.ex.margined = [{"product_id": 900, "size": "-4"}]
        report = observe_exposure_without_margin(self.ex)
        self.assertEqual(report["account_wide_margined_positions_nonzero"], 1)
        self.assertTrue(report["any_exposure_observed"])
        self.assertEqual(report["blocker"], "exposure_present")
        self.assertFalse(report["trade_authorized"])

    def test_pending_order_on_other_market_cannot_be_missed(self):
        self.ex.orders = [{"id": 9001, "product_id": 900, "state": "pending"}]
        report = observe_exposure_without_margin(self.ex)
        self.assertEqual(report["account_wide_open_or_pending_orders"], 1)
        self.assertTrue(report["any_exposure_observed"])
        self.assertNotIn("9001", json.dumps(report))
        self.assertNotIn('"900"', json.dumps(report))

    def test_stale_margined_snapshot_with_active_realtime_market_is_not_flat(self):
        self.ex.live[27] = "2"
        report = observe_exposure_without_margin(self.ex)
        self.assertEqual(report["blocker"], "margined_realtime_position_disagreement")
        self.assertTrue(report["any_exposure_observed"])
        self.assertFalse(report["margined_realtime_consistent"])

    def test_broker_position_and_realtime_consistent_is_not_trade_authority(self):
        self.ex.margined = [{"product_id": 27, "size": "2"}]
        self.ex.live[27] = "2"
        report = observe_exposure_without_margin(self.ex)
        self.assertEqual(report["blocker"], "exposure_present")
        self.assertTrue(report["margined_realtime_consistent"])
        self.assertFalse(report["safe_to_enable_fire"])

    def test_pagination_cursor_rejects_incomplete_order_inventory(self):
        self.ex.orders_cursor = "next-page"
        report = observe_exposure_without_margin(self.ex)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stage"], "account_orders_all_pages")
        self.assertIsNone(report["account_wide_open_or_pending_orders"])
        self.assertFalse(report["safe_to_deploy"])

    def test_margined_next_page_is_not_silently_ignored(self):
        self.ex.margin_meta = {"after": "another-page"}
        report = observe_exposure_without_margin(self.ex)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stage"], "account_margined_positions")
        self.assertIsNone(report["account_wide_margined_positions_nonzero"])

    def test_bad_source_or_invalid_numeric_fails_closed_and_redacts(self):
        for margined in (
            [{"product_id": 800, "size": "NaN"}],
            [{"product_id": 800, "size": "1"}, {"product_id": 800, "size": "1"}],
            [{"size": "1"}],
            [None],
        ):
            with self.subTest(margined=margined):
                self.ex.margined = margined
                report = observe_exposure_without_margin(self.ex)
                self.assertEqual(report["status"], "blocked")
                self.assertIsNone(report["account_wide_margined_positions_nonzero"])
                self.assertFalse(report["trade_authorized"])

    def test_exception_body_never_appears_in_report(self):
        self.ex.invalid_path = "/v2/orders"
        report = observe_exposure_without_margin(self.ex)
        self.assertEqual(report["status"], "blocked")
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertNotIn("SECRET", json.dumps(report))

    def test_order_capable_or_wrong_environment_client_rejected_before_api(self):
        self.ex.allow_orders = True
        report = observe_exposure_without_margin(self.ex)
        self.assertEqual(report["blocker"], "read_only_delta_demo_client_required")
        self.assertEqual(self.ex.calls, [])


if __name__ == "__main__":
    unittest.main()
