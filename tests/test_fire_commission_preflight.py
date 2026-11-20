"""Offline fail-closed tests for the operator-only Gold commissioning gate."""
import unittest
from unittest.mock import patch

from tradebot.delta import DEMO_API
from tradebot.fire_commission_preflight import commissioning_preflight


def flat_gate():
    return {
        "broker_flat_two_samples": True,
        "samples_checked": 2,
        "positions": 0,
        "open_orders": 0,
        "unresolved_fire_receipts": 0,
        "account_margin_mode": "isolated",
        "blockers": [],
    }


class FakeReadOnlyDemo:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self):
        self.calls = []
        self.product_tick = "0.01"
        self.leverage = 20

    def ticker(self, symbol):
        self.calls.append(("GET", "ticker"))
        return {
            "symbol": symbol, "product_id": 82, "tick_size": "0.01"
        }

    def _request(self, method, path, *, auth=False):
        self.calls.append((method, path))
        assert method == "GET"
        if path == "/v2/products/XAUTUSD":
            return {"result": {
                "symbol": "XAUTUSD", "id": 82,
                "tick_size": self.product_tick,
                "contract_type": "perpetual_futures",
            }}
        if path == "/v2/products/82/orders/leverage":
            assert auth
            return {"result": {"product_id": 82, "leverage": self.leverage}}
        raise AssertionError("Unexpected broker path")


class CommissioningPreflightTests(unittest.TestCase):
    def setUp(self):
        self.exchange = FakeReadOnlyDemo()

    def run_gate(self, *, gate=None, services=lambda: True, fire=lambda: True):
        with patch(
            "tradebot.fire_commission_preflight.verify_staging_samples",
            return_value=flat_gate() if gate is None else gate,
        ):
            return commissioning_preflight(
                self.exchange, "/fake/data",
                pause=lambda _: None, check_services=services, check_fire=fire
            )

    def test_ready_is_read_only_and_never_trade_authority(self):
        result = self.run_gate()
        self.assertTrue(result["ready_for_supervised_operator_review"])
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(result["broker_liquidation_price_verified"])
        self.assertFalse(result["order_mutations"])
        self.assertEqual(result["ai_calls"], 0)
        self.assertEqual(result["gold_tick_size"], "0.01")
        self.assertEqual(result["gold_leverage"], 20)
        self.assertEqual(result["blockers"], [])
        self.assertTrue(all(method == "GET" for method, _ in self.exchange.calls))

    def test_fire_enabled_blocks_commission_readiness(self):
        result = self.run_gate(fire=lambda: False)
        self.assertFalse(result["ready_for_supervised_operator_review"])
        self.assertIn("fire_execution_not_disabled", result["blockers"])

    def test_missing_watchdog_blocks_commission_readiness(self):
        result = self.run_gate(services=lambda: False)
        self.assertIn("dashboard_or_watchdog_not_active", result["blockers"])

    def test_one_broker_sample_does_not_pass(self):
        incomplete = {**flat_gate(), "samples_checked": 1}
        result = self.run_gate(gate=incomplete)
        self.assertIn("account_wide_broker_release_gate_not_passed", result["blockers"])

    def test_missing_broker_tick_rejected(self):
        self.exchange.product_tick = None
        result = self.run_gate()
        self.assertIn("gold_product_or_leverage_not_verified", result["blockers"])

    def test_broker_leverage_above_cap_rejected(self):
        self.exchange.leverage = 21
        result = self.run_gate()
        self.assertIn("gold_product_or_leverage_not_verified", result["blockers"])

    def test_mutation_enabled_exchange_refused_before_broker_read(self):
        self.exchange.allow_orders = True
        result = self.run_gate()
        self.assertIn("read_only_delta_demo_client_required", result["blockers"])
        self.assertEqual(self.exchange.calls, [])

    def test_endpoint_error_fails_closed_without_leaking_exception(self):
        def offline():
            raise OSError("secret:error")
        result = self.run_gate(fire=offline)
        self.assertIn("fire_execution_status_unavailable", result["blockers"])
        self.assertNotIn("secret:error", str(result))


if __name__ == "__main__":
    unittest.main()
