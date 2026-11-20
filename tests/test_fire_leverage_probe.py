"""No-mutation dynamic-leverage broker compatibility tests."""
import unittest

from tradebot.delta import DEMO_API
from tradebot.fire_leverage_probe import audit_leverage_broker


class FakeMarket:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self, symbol, pid, *, size=0, leverage=5, liq="60000",
                 margin_mode="isolated", errors=False):
        self.symbol = symbol
        self.product_id = pid
        self.size = size
        self.leverage = leverage
        self.liq = liq
        self.margin_mode = margin_mode
        self.errors = errors
        self.calls = []

    def positions(self):
        self.calls.append("positions")
        if self.errors:
            raise RuntimeError("SENSITIVE_KEY_SHOULD_NOT_LEAK")
        return [{"product_id": self.product_id, "size": self.size,
                 "entry_price": "63214.25"}] if self.size else []

    def open_orders(self):
        self.calls.append("open_orders")
        return []

    def _request(self, method, path, *, params=None, auth=False):
        self.calls.append((method, path))
        assert method == "GET" and auth
        if path.endswith("/orders/leverage"):
            return {"result": {"product_id": self.product_id,
                               "leverage": self.leverage}}
        if path == "/v2/positions/margined":
            assert params == {"product_ids": str(self.product_id)}
            return {"result": [{"product_id": self.product_id, "size": self.size,
                               "entry_price": "63214.25",
                               "margin_mode": self.margin_mode,
                               "liquidation_price": self.liq}]}
        raise AssertionError("unexpected broker request")


class BrokerCompatibilityTests(unittest.TestCase):
    def markets(self, *, size=0, leverage=5, liq="60000", margin_mode="isolated"):
        return {
            "BTCUSD": FakeMarket("BTCUSD", 27, size=size,
                                leverage=leverage, liq=liq, margin_mode=margin_mode),
            "XAUTUSD": FakeMarket("XAUTUSD", 82),
        }

    def test_flat_probe_only_gets_and_never_authorizes_deploy(self):
        markets = self.markets()
        result = audit_leverage_broker(markets)
        self.assertEqual(result["blockers"], [])
        self.assertFalse(result["safe_to_deploy"])
        self.assertFalse(result["order_mutations"])
        self.assertEqual(result["ai_calls"], 0)
        for broker in markets.values():
            self.assertTrue(all(method == "GET" for method, _ in broker.calls
                                if isinstance(method, str) and method == "GET"))

    def test_active_btc_reports_evidence_but_prevents_release(self):
        result = audit_leverage_broker(self.markets(size=-20, leverage=100))
        btc = result["markets"]["BTCUSD"]
        self.assertEqual(btc["liquidation_price"], "60000")
        self.assertTrue(btc["margin_evidence_verified"])
        self.assertEqual(btc["position_contracts"], -20)
        self.assertIn("btcusd_has_exposure", result["blockers"])
        self.assertIn("btcusd_leverage_above_20x", result["blockers"])
        self.assertFalse(result["safe_to_deploy"])

    def test_missing_liquidation_or_nonisolated_margin_is_not_safe(self):
        for opts in ({"liq": None}, {"margin_mode": "portfolio"}):
            with self.subTest(opts=opts):
                report = audit_leverage_broker(self.markets(size=1, **opts))
                self.assertTrue(report["blockers"])
                self.assertFalse(report["safe_to_deploy"])

    def test_errors_never_leak_secrets_and_keep_deployment_blocked(self):
        markets = self.markets()
        markets["BTCUSD"].errors = True
        report = audit_leverage_broker(markets)
        self.assertIn("btcusd_broker_evidence_unverified", report["blockers"])
        self.assertNotIn("SENSITIVE_KEY_SHOULD_NOT_LEAK", str(report))
        self.assertFalse(report["safe_to_deploy"])

    def test_unknown_client_rejected_without_network(self):
        markets = self.markets()
        markets["BTCUSD"].base_url = "https://api.india.delta.exchange"
        report = audit_leverage_broker(markets)
        self.assertIn("btcusd_read_only_demo_required", report["blockers"])
        self.assertEqual(markets["BTCUSD"].calls, [])

    def test_all_markets_are_mandatory(self):
        report = audit_leverage_broker({"BTCUSD": self.markets()["BTCUSD"]})
        self.assertEqual(report["blockers"], ["both_fire_markets_required"])


if __name__ == "__main__":
    unittest.main()
