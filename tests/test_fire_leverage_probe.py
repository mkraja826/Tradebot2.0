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
        self.account_markets = None
        self.other_positions = []
        self.other_orders = []
        self.pagination_after = None
        self.leverage_has_product_identity = True

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
            result = {"leverage": self.leverage}
            if self.leverage_has_product_identity:
                result["product_id"] = self.product_id
            return {"result": result}
        if path == "/v2/users/trading_preferences":
            return {"result": {"user_id": 501}}
        if path == "/v2/sub_accounts":
            return {"result": [{"id": 501, "margin_mode": self.margin_mode}]}
        if path == "/v2/positions/margined":
            if params is None:
                rows = [
                    {"product_id": m.product_id, "size": m.size,
                     "entry_price": "63214.25"} for m in self.account_markets.values()
                    if m.size]
                return {"result": rows + self.other_positions}
            assert params == {"product_ids": str(self.product_id)}
            return {"result": [{"product_id": self.product_id, "size": self.size,
                               "entry_price": "63214.25",
                               "margin_mode": self.margin_mode,
                               "liquidation_price": self.liq}]}
        if path == "/v2/orders":
            assert params["states"] == "open,pending"
            assert params["page_size"] == 50
            return {"result": self.other_orders,
                    "meta": {"after": self.pagination_after}}
        if path.startswith("/v2/products/"):
            symbol = path.split("/")[-1]
            m = self.account_markets[symbol]
            return {"result": {"symbol": symbol, "id": m.product_id,
                               "contract_type": "perpetual_futures"}}
        if path == "/v2/positions":
            market = next(m for m in self.account_markets.values()
                          if m.product_id == params["product_id"])
            return {"result": [{
                "product_id": market.product_id, "size": market.size,
                "entry_price": "63214.25",
            }] if market.size else []}
        raise AssertionError("unexpected broker request")


class BrokerCompatibilityTests(unittest.TestCase):
    def markets(self, *, size=0, leverage=5, liq="60000", margin_mode="isolated"):
        markets = {
            "BTCUSD": FakeMarket("BTCUSD", 27, size=size,
                                leverage=leverage, liq=liq, margin_mode=margin_mode),
            "XAUTUSD": FakeMarket("XAUTUSD", 82, margin_mode=margin_mode),
        }
        for market in markets.values():
            market.account_markets = markets
        return markets

    def test_flat_probe_only_gets_and_never_authorizes_deploy(self):
        markets = self.markets()
        result = audit_leverage_broker(markets)
        self.assertEqual(result["blockers"], [])
        self.assertTrue(result["account_wide"]["sampled"])
        self.assertTrue(result["account_wide"]["isolated_margin_observed"])
        self.assertEqual(result["account_wide"]["nonzero_margined_positions"], 0)
        self.assertEqual(result["account_wide"]["open_orders"], 0)
        self.assertTrue(result["account_wide"]["margined_fire_consistency"])
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(result["safe_to_enable_fire"])
        self.assertFalse(result["safe_to_deploy"])
        self.assertFalse(result["order_mutations"])
        self.assertEqual(result["ai_calls"], 0)
        for broker in markets.values():
            self.assertTrue(all(call[0] == "GET" for call in broker.calls
                                if isinstance(call, tuple)))

    def test_flat_portfolio_margin_blocks_broker_commissioning(self):
        result = audit_leverage_broker(self.markets(margin_mode="portfolio"))
        self.assertIn("btcusd_isolated_margin_required", result["blockers"])
        self.assertFalse(result["safe_to_deploy"])
        self.assertEqual(result["markets"]["BTCUSD"]["margin_mode"], "portfolio")

    def test_other_product_position_blocks_even_when_both_fire_markets_flat(self):
        markets = self.markets()
        markets["BTCUSD"].other_positions = [{"product_id": 999, "size": "4"}]
        result = audit_leverage_broker(markets)
        self.assertEqual(result["markets"]["BTCUSD"]["position_contracts"], 0)
        self.assertEqual(result["markets"]["XAUTUSD"]["position_contracts"], 0)
        self.assertIn("account_has_margined_exposure", result["blockers"])
        self.assertEqual(result["account_wide"]["nonzero_margined_positions"], 1)
        self.assertFalse(result["safe_to_enable_fire"])

    def test_other_product_open_order_blocks_even_when_fire_orders_empty(self):
        markets = self.markets()
        markets["BTCUSD"].other_orders = [{"id": "some-order", "product_id": 999}]
        report = audit_leverage_broker(markets)
        self.assertIn("account_has_open_orders", report["blockers"])
        self.assertEqual(report["account_wide"]["open_orders"], 1)
        self.assertEqual(report["markets"]["BTCUSD"]["open_orders"], 0)
        self.assertEqual(report["markets"]["XAUTUSD"]["open_orders"], 0)

    def test_account_order_cursor_blocks_incomplete_pagination(self):
        markets = self.markets()
        markets["BTCUSD"].pagination_after = "uninspected-page"
        report = audit_leverage_broker(markets)
        self.assertIn("account_wide_broker_evidence_unverified",
                      report["blockers"])
        self.assertFalse(report["account_wide"]["sampled"])
        self.assertFalse(report["trade_authorized"])

    def test_account_realtime_margined_mismatch_blocks(self):
        markets = self.markets()
        orig = markets["BTCUSD"]._request

        def inconsistent(method, path, *, params=None, auth=False):
            response = orig(method, path, params=params, auth=auth)
            if path == "/v2/positions" and params == {"product_id": 27}:
                return {"result": [{"product_id": 27, "size": "1"}]}
            return response

        markets["BTCUSD"]._request = inconsistent
        report = audit_leverage_broker(markets)
        self.assertIn("account_margined_realtime_positions_conflict",
                      report["blockers"])
        self.assertIn("btcusd_exposure_changed_during_probe", report["blockers"])

    def test_account_profile_margin_nonisolated_blocks_even_when_flat(self):
        markets = self.markets(margin_mode="portfolio")
        report = audit_leverage_broker(markets)
        self.assertIn("account_isolated_margin_unverified", report["blockers"])
        self.assertIn("btcusd_isolated_margin_required", report["blockers"])

    def test_missing_leverage_product_id_never_counted_as_verified(self):
        markets = self.markets()
        markets["BTCUSD"].leverage_has_product_identity = False
        report = audit_leverage_broker(markets)
        self.assertIn("btcusd_broker_evidence_unverified", report["blockers"])
        self.assertIsNone(report["markets"]["BTCUSD"]["configured_leverage"])
        self.assertFalse(report["safe_to_enable_fire"])

    def test_fractional_or_subunit_leverage_is_unverified(self):
        for leverage in ("0.5", "1.5", 0, "not-a-number"):
            with self.subTest(leverage=leverage):
                report = audit_leverage_broker(self.markets(leverage=leverage))
                self.assertIn("btcusd_broker_evidence_unverified", report["blockers"])
                self.assertFalse(report["safe_to_deploy"])

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
