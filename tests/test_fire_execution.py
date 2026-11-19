"""Offline GPT-6 one-tap Demo FIRE with actual mock POST and bracket verification."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from tradebot.delta import DEMO_API, DeltaError
from tradebot.fire_execution import (
    FireDemoController, FireTradeStore, protective_orders_verified,
)


def snapshot():
    return {
        "environment": "delta-india-demo",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "position_contracts": 0,
        "core": {
            "best_bid": "63214.0", "best_ask": "63214.5",
            "ticker": {"product_id": 27, "symbol": "BTCUSD",
                       "contract_type": "perpetual_futures", "mark_price": "63214.25"},
        },
    }


PLAN = {"direction": "LONG", "contracts": 1,
        "stop_loss": "62950", "take_profit": "63950"}


class FakeDemo:
    base_url = DEMO_API
    allow_orders = True

    def __init__(self):
        self.requests = []
        self.position = 0
        self.with_brackets = True
        self.submit_timeout = False
        self.active_orders = []
        self.order = None
        self.leverage = 5

    def ticker(self, symbol):
        return {
            "symbol": "BTCUSD", "product_id": 27,
            "mark_price": "63214.25",
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
            "quotes": {"best_bid": "63214", "best_ask": "63214.5"},
        }

    def btc_positions(self):
        return ([{"product_id": 27, "size": str(self.position),
                  "product_symbol": "BTCUSD"}] if self.position else [])

    def open_orders(self):
        return list(self.active_orders)

    def wallet_balances(self):
        return {"meta": {"net_equity": "173.81"},
                "balances": [{"asset_symbol": "USD", "available_balance": "173.81"}]}

    def _request(self, method, path, *, auth=False, payload=None):
        if method == "GET" and path.endswith("/orders/leverage"):
            return {"result": {"leverage": self.leverage, "product_id": 27}}
        if method == "GET" and path == "/v2/products/BTCUSD":
            return {"result": {"id": 27, "symbol": "BTCUSD", "contract_type": "perpetual_futures",
                               "settling_asset": {"symbol": "USD"}, "notional_type": "vanilla",
                               "initial_margin": "0.5", "contract_value": "0.001", "taker_commission_rate": "0.0005"}}

        self.requests.append((method, path, payload))
        if self.submit_timeout:
            raise TimeoutError("response lost, possible fill")
        self.position = payload["size"] if payload["side"] == "buy" else -payload["size"]
        self.order = {
            "id": 1234, "client_order_id": payload["client_order_id"],
            "product_id": 27, "state": "closed", "unfilled_size": 0,
            "bracket_stop_loss_price": payload["bracket_stop_loss_price"],
            "bracket_take_profit_price": payload["bracket_take_profit_price"],
        }
        if self.with_brackets:
            side = "sell" if self.position > 0 else "buy"
            self.active_orders = [
                {"id": 9991, "product_id": 27, "stop_order_type": "stop_loss_order",
                 "bracket_order": True, "side": side, "state": "pending",
                 "stop_price": payload["bracket_stop_loss_price"],
                 "product_symbol": "BTCUSD"},
                {"id": 9992, "product_id": 27, "stop_order_type": "take_profit_order",
                 "bracket_order": True, "side": side, "state": "pending",
                 "stop_price": payload["bracket_take_profit_price"],
                 "product_symbol": "BTCUSD"},
            ]
        return {"result": self.order}

    def order_by_client_id(self, order_id):
        if self.order:
            return self.order
        raise DeltaError("No matching broker order")

    def cancel_product_orders(self, product_id):
        self.active_orders = []

    def products(self):
        return [{"id": 27, "symbol": "BTCUSD", "contract_type": "perpetual_futures",
                 "state": "live"}]

    def place_order(self, **kwargs):
        if not kwargs.get("reduce_only"):
            raise AssertionError("No additional ENTRY allowed")
        self.position = 0
        return {"id": 987}


class FireExecutionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "fire-ops.sqlite"
        self.exchange = FakeDemo()
        self.calls = []

    def make(self, *, enabled=True, plan=None):
        p = plan or PLAN
        def model(routes, loader):
            self.calls.append(routes)
            loader()
            return {"results": {"fire": {"decision": p}}}
        return FireDemoController(
            self.path, enabled=enabled,
            exchange_factory=lambda: self.exchange,
            snapshot_loader=snapshot,
            probe=model, spawn=lambda callback: callback(),
            pause=lambda seconds: None,
        )

    def test_one_click_posts_one_order_and_verifies_both_protective_stops(self):
        fire = self.make()
        accepted, _ = fire.start()
        self.assertTrue(accepted)
        state = fire.snapshot()
        self.assertEqual(state["status"], "protected_active")
        self.assertTrue(state["protection_verified"])
        self.assertTrue(state["orders_submitted"])
        self.assertEqual(state["model"], "tb-gpt-6")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.exchange.requests), 1)
        method, path, payload = self.exchange.requests[0]
        self.assertEqual((method, path), ("POST", "/v2/orders"))
        self.assertEqual(payload["bracket_stop_trigger_method"], "mark_price")
        self.assertEqual(payload["bracket_stop_loss_price"], "62950")
        self.assertEqual(payload["bracket_take_profit_price"], "63950")
        self.assertEqual(payload["size"], 1)
        self.assertEqual(payload["side"], "buy")
        self.assertFalse(fire.start()[0])
        self.assertEqual(len(self.exchange.requests), 1)
        self.assertFalse(self.make().start()[0])  # persistent across restart

    def test_multiple_contracts_exceed_verified_risk_despite_margin_capacity(self):
        fire = self.make(plan=PLAN | {"contracts": 2})
        fire.start()
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "risk_governor_failed")
        self.assertEqual(fire.snapshot()["budget"]["max_contracts_per_entry"], 2)
        self.assertEqual(self.exchange.requests, [])

    def test_unsafe_broker_leverage_blocks_paid_ai_and_order(self):
        self.exchange.leverage = 100
        fire = self.make()
        fire.start()
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "margin_budget_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_insufficient_reward_to_risk_fails_closed(self):
        fire = self.make(plan=PLAN | {"take_profit": "63250"})
        fire.start()
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "risk_governor_failed")
        self.assertEqual(self.exchange.requests, [])

    def test_equity_drop_before_submission_recomputes_budget(self):
        from unittest.mock import patch
        full = self.exchange.wallet_balances()
        reduced = dict(full, meta={"net_equity": "3"})
        with patch.object(self.exchange, "wallet_balances", side_effect=[full, reduced]):
            fire = self.make()
            fire.start()
            self.assertEqual(fire.snapshot()["reason_code"], "margin_budget_recheck_failed")
            self.assertEqual(self.exchange.requests, [])

    def test_free_usd_and_reserved_fees_can_lower_contract_limit(self):
        from unittest.mock import patch
        funds = self.exchange.wallet_balances()
        funds["balances"][0]["available_balance"] = "0.65"
        with patch.object(self.exchange, "wallet_balances", return_value=funds):
            fire = self.make()
            fire.start()
            self.assertEqual(fire.snapshot()["budget"]["max_contracts_per_entry"], 0)
            self.assertFalse(self.calls)
            self.assertFalse(self.exchange.requests)

    def test_quarantined_historical_levels_block_paid_ai_and_execution(self):
        class UnverifiedArchive:
            def levels(self, symbol, at, price):
                return {"periods": {
                    key: {"quality_status": "quarantined"}
                    for key in ("day","previous_day","week","previous_week",
                                "month","previous_month")
                }}
        fire = self.make()
        fire.archive = UnverifiedArchive()
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["status"],"rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"],"historical_data_integrity_failed")
        self.assertEqual(self.calls,[])
        self.assertEqual(self.exchange.requests,[])

    def test_existing_order_consumes_market_before_model_call(self):
        self.exchange.active_orders = [{"id": 99, "product_id": 27, "size": 2}]
        fire = self.make()
        fire.start()
        self.assertEqual(fire.snapshot()["reason_code"], "market_availability_failed")
        self.assertFalse(self.calls)
        self.assertFalse(self.exchange.requests)

    def test_unverified_protection_forces_emergency_closeout(self):
        self.exchange.with_brackets = False
        fire = self.make()
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["status"], "flat_verified")
        self.assertFalse(fire.snapshot()["protection_verified"])
        self.assertEqual(fire.snapshot()["reason_code"], "emergency_flat_verified")
        self.assertEqual(self.exchange.position, 0)

    def test_new_manual_order_between_checks_is_not_cancelled(self):
        class RacingBroker(FakeDemo):
            def __init__(self):
                super().__init__()
                self.read_count = 0
                self.cancel_count = 0

            def open_orders(self):
                self.read_count += 1
                if self.read_count <= 2:
                    return []
                return [{"id": 42, "product_id": 27,
                         "product_symbol": "BTCUSD", "state": "open"}]

            def cancel_product_orders(self, product_id):
                self.cancel_count += 1

        self.exchange = RacingBroker()
        fire = self.make()
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "no_durable_broker_intent")
        self.assertEqual(self.exchange.cancel_count, 0)
        self.assertEqual(self.exchange.requests, [])

    def test_broker_timeout_is_not_retried_and_exposure_is_closed(self):
        self.exchange.submit_timeout = True
        fire = self.make()
        self.assertTrue(fire.start()[0])
        self.assertEqual(len(self.exchange.requests), 1)
        self.assertEqual(fire.snapshot()["status"], "flat_verified")
        self.assertEqual(fire.snapshot()["reason_code"], "emergency_flat_verified")

    def test_disabled_fire_makes_no_paid_ai_or_exchange_requests(self):
        fire = self.make(enabled=False)
        self.assertEqual(fire.start(), (False, "execution_disabled"))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_market_budget_rejects_oversize_ai_plan_before_order(self):
        fire = self.make(plan=PLAN | {"contracts": 56})
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["orders_submitted"], False)
        self.assertEqual(len(self.exchange.requests), 0)

    def test_protection_requires_two_distinct_valid_opposite_side_brackets(self):
        self.exchange.position = 1
        self.exchange.active_orders = [
            {"id": 11, "product_id": 27, "bracket_order": True,
             "stop_order_type": "stop_loss_order", "state": "pending",
             "side": "sell", "stop_price": "62950"},
            {"id": 12, "product_id": 27, "bracket_order": True,
             "stop_order_type": "take_profit_order", "state": "pending",
             "side": "sell", "stop_price": "63950"},
        ]
        self.assertTrue(protective_orders_verified(self.exchange.active_orders,
                       product_id=27, plan=PLAN))
        invalid = list(self.exchange.active_orders)
        invalid[1] = dict(invalid[1], id=11)
        self.assertFalse(protective_orders_verified(invalid, product_id=27, plan=PLAN))
        invalid[1] = dict(invalid[1], stop_price="63800")
        self.assertFalse(protective_orders_verified(invalid, product_id=27, plan=PLAN))

    def test_provider_rejection_is_visible_on_receipt_without_order(self):
        fire = self.make()
        fire.probe = lambda *_: {"results": {"fire": {"error": "Top Billing API HTTP 429", "latency_ms": 225}}}
        fire.start()
        state = fire.snapshot()
        self.assertEqual(state["reason_code"], "provider_http_429")
        self.assertEqual(state["model_latency_ms"], 225)
        self.assertFalse(state["orders_submitted"])
        self.assertFalse(self.exchange.requests)

    def test_read_failed_model_never_posts_to_exchange(self):
        fire = self.make(plan=PLAN | {"stop_loss": "64000"})
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(len(self.exchange.requests), 0)


if __name__ == "__main__":
    unittest.main()
