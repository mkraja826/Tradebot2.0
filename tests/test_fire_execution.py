"""Offline GPT-6 one-tap Demo FIRE with actual mock POST and bracket verification."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from equity_fixtures import receipt_for

from tradebot.delta import DEMO_API, DeltaError
from tradebot.fire_leverage import verify_liquidation_clearance
from tradebot.portfolio_equity_guard import PortfolioEquityGuard
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


def seed_demo_equity(path, equity):
    """Populate actual-shaped UTC period opening observations for offline mocks."""
    now = datetime.now(timezone.utc)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = day - timedelta(days=day.weekday())
    guard = PortfolioEquityGuard(Path(path).parent / "fire-equity-risk.sqlite")
    guard.observe_verified_read(equity, receipt_for(equity, monday), now=monday)
    if day != monday:
        guard.observe_verified_read(equity, receipt_for(equity, day), now=day)
    return guard


PLAN = {"direction": "LONG", "contracts": 1, "leverage": 5,
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
        self.leverage_changes = []
        self.ignore_leverage_change = False
        self.liquidation_price = "60000"
        self.margin_mode = "isolated"
        self.other_positions = []
        self.other_open_orders = []

    def ticker(self, symbol):
        return {
            "symbol": "BTCUSD", "product_id": 27,
            "tick_size": "0.5", "mark_price": "63214.25",
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
            "quotes": {"best_bid": "63214", "best_ask": "63214.5"},
        }

    def btc_positions(self):
        return ([{"product_id": 27, "size": str(self.position),
                  "product_symbol": "BTCUSD", "entry_price": "63214.25"}] if self.position else [])

    def open_orders(self):
        return list(self.active_orders)

    def wallet_balances(self):
        return {"meta": {"net_equity": "173.81"},
                "equity_read_receipt": receipt_for("173.81"),
                "balances": [{"asset_symbol": "USD", "available_balance": "173.81"}]}

    def _request(self, method, path, *, auth=False, payload=None, params=None):
        if method == "GET" and path == "/v2/profile":
            return {"result": {"margin_mode": self.margin_mode}}
        if method == "GET" and path == "/v2/positions/margined":
            return {"result": ([{"product_id": 27, "size": self.position,
                                 "margin_mode": self.margin_mode,
                                 "entry_price": "63214.25",
                                 "liquidation_price": self.liquidation_price}]
                                if self.position else []) + self.other_positions}
        if method == "GET" and path == "/v2/positions":
            assert params and params.get("product_id") in (27, 82)
            return {"result": ({"size": self.position, "product_id": 27,
                                "entry_price": "63214.25"} if params["product_id"] == 27
                               else {"size": 0, "product_id": 82, "entry_price": "0"})}
        if method == "GET" and path == "/v2/orders":
            return {"result": self.active_orders + self.other_open_orders,
                    "meta": {"after": None}}
        if method == "POST" and path.endswith("/orders/leverage"):
            self.leverage_changes.append(payload)
            if not self.ignore_leverage_change:
                self.leverage = int(payload["leverage"])
            return {"result": {"product_id": 27, "leverage": payload["leverage"]}}
        if method == "GET" and path.endswith("/orders/leverage"):
            return {"result": {"leverage": self.leverage, "product_id": 27}}
        if method == "GET" and path == "/v2/products/BTCUSD":
            return {"result": {"id": 27, "symbol": "BTCUSD", "contract_type": "perpetual_futures",
                               "settling_asset": {"symbol": "USD"}, "notional_type": "vanilla",
                               "initial_margin": "0.5", "contract_value": "0.001",
                               "tick_size": "0.5", "taker_commission_rate": "0.0005"}}
        if method == "GET" and path == "/v2/products/XAUTUSD":
            return {"result": {"id": 82, "symbol": "XAUTUSD",
                               "contract_type": "perpetual_futures"}}

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
                 "stop_price": payload["bracket_stop_loss_price"], "size": payload["size"],
                 "product_symbol": "BTCUSD"},
                {"id": 9992, "product_id": 27, "stop_order_type": "take_profit_order",
                 "bracket_order": True, "side": side, "state": "pending",
                 "stop_price": payload["bracket_take_profit_price"], "size": payload["size"],
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
        seed_demo_equity(self.path, "173.81")
        self.calls = []

    def make(self, *, enabled=True, plan=None):
        p = plan or PLAN
        def model(routes, loader):
            self.calls.append(routes)
            loader()
            return {"results": {"fire": {"decision": p}}}
        desk = FireDemoController(
            self.path, enabled=enabled,
            exchange_factory=lambda: self.exchange,
            snapshot_loader=snapshot,
            probe=model, spawn=lambda callback: callback(),
            pause=lambda seconds: None,
        )
        class ValidArchive:
            def levels(self, symbol, at, price):
                return {"periods": {
                    key: {"quality_status": "provisionally_valid"}
                    for key in ("day", "previous_day", "week", "previous_week",
                                "month", "previous_month")
                }}
        # Test fixtures deliberately make the mandatory historical gate pass.
        # Production must use an actual checked candle archive.
        desk.archive = ValidArchive()
        return desk

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

    def test_off_tick_stop_rejected_before_order_mutation(self):
        fire = self.make(plan=PLAN | {"stop_loss": "62950.13"})
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "exchange_preflight_failed")
        self.assertFalse(self.exchange.requests)

    def test_off_tick_target_rejected_before_order_mutation(self):
        fire = self.make(plan=PLAN | {"take_profit": "63950.13"})
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["reason_code"], "exchange_preflight_failed")
        self.assertFalse(self.exchange.requests)

    def test_unknown_broker_tick_rejected_without_order(self):
        get = self.exchange._request
        def remove_tick(method, path, **kwargs):
            reply = get(method, path, **kwargs)
            if path == "/v2/products/BTCUSD":
                reply["result"].pop("tick_size", None)
            return reply
        self.exchange._request = remove_tick
        fire = self.make()
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["reason_code"], "exchange_preflight_failed")
        self.assertFalse(self.exchange.requests)

    def test_gpt6_can_select_lower_leverage_after_flat_verified_preflight(self):
        fire = self.make(plan=PLAN | {"leverage": 3})
        self.assertTrue(fire.start()[0])
        state = fire.snapshot()
        self.assertEqual(state["status"], "protected_active")
        self.assertEqual(state["selected_leverage"], 3)
        self.assertEqual(state["budget"]["leverage"], "3")
        self.assertTrue(state["liquidation_verified"])
        self.assertEqual(self.exchange.leverage_changes, [{"leverage": "3"}])
        self.assertEqual(len(self.exchange.requests), 1)

    def test_broker_leverage_readback_mismatch_blocks_order(self):
        self.exchange.ignore_leverage_change = True
        fire = self.make(plan=PLAN | {"leverage": 3})
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "leverage_sync_failed")
        self.assertEqual(self.exchange.requests, [])

    def test_liquidation_inside_stop_triggers_emergency_flat(self):
        self.exchange.liquidation_price = "63150"
        fire = self.make()
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["status"], "flat_verified")
        self.assertEqual(fire.snapshot()["reason_code"], "emergency_flat_verified")
        self.assertFalse(fire.snapshot()["protection_verified"])
        self.assertEqual(self.exchange.position, 0)

    def test_proven_unsafe_liquidation_emergency_closes_without_11_second_retry(self):
        self.exchange.liquidation_price = "63150"
        with patch("tradebot.fire_execution.verify_liquidation_clearance",
                   wraps=verify_liquidation_clearance) as clearance:
            fire = self.make()
            fire.start()
        self.assertEqual(clearance.call_count, 1)
        self.assertEqual(fire.snapshot()["status"], "flat_verified")
        self.assertEqual(fire.snapshot()["reason_code"], "emergency_flat_verified")
        self.assertEqual(self.exchange.position, 0)

    def test_unrelated_margin_position_blocks_before_paid_gpt(self):
        self.exchange.other_positions = [{"product_id": 999, "size": "-5"}]
        fire = self.make()
        fire.start()
        self.assertEqual(fire.snapshot()["reason_code"], "account_exposure_preflight_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_other_market_pending_order_blocks_before_paid_gpt(self):
        self.exchange.other_open_orders = [{"id": 12, "product_id": 82}]
        fire = self.make()
        fire.start()
        self.assertEqual(fire.snapshot()["reason_code"], "account_exposure_preflight_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_missing_order_pagination_metadata_never_proves_flat(self):
        original = self.exchange._request
        def missing_meta(method, path, **kwargs):
            if method == "GET" and path == "/v2/orders":
                return {"result": []}
            return original(method, path, **kwargs)
        self.exchange._request = missing_meta
        fire = self.make()
        fire.start()
        self.assertEqual(fire.snapshot()["reason_code"],
                         "account_exposure_preflight_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_global_position_continuation_never_proves_flat(self):
        original = self.exchange._request
        def partial(method, path, **kwargs):
            if method == "GET" and path == "/v2/positions/margined":
                return {"result": [], "meta": {"after": "next-page"}}
            return original(method, path, **kwargs)
        self.exchange._request = partial
        fire = self.make()
        fire.start()
        self.assertEqual(fire.snapshot()["reason_code"],
                         "account_exposure_preflight_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_realtime_position_continuation_never_proves_flat(self):
        original = self.exchange._request
        def partial(method, path, **kwargs):
            if method == "GET" and path == "/v2/positions":
                return {"result": [], "meta": {"after": "next-page"}}
            return original(method, path, **kwargs)
        self.exchange._request = partial
        fire = self.make()
        fire.start()
        self.assertEqual(fire.snapshot()["reason_code"],
                         "account_exposure_preflight_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_portfolio_change_after_model_blocks_order(self):
        original = self.exchange._request
        count = [0]
        def race(method, path, **kwargs):
            if path == "/v2/positions/margined":
                count[0] += 1
                if count[0] > 1:
                    return {"result": [{"product_id": 999, "size": 1}]}
            return original(method, path, **kwargs)
        self.exchange._request = race
        fire = self.make()
        fire.start()
        self.assertEqual(fire.snapshot()["reason_code"], "account_exposure_recheck_failed")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.exchange.requests, [])

    def test_multiple_contracts_rejected_by_backend_pilot_cap(self):
        fire = self.make(plan=PLAN | {"contracts": 2})
        fire.start()
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "contract_size_failed")
        self.assertEqual(fire.snapshot()["budget"]["max_contracts_per_entry"], 1)
        self.assertEqual(self.exchange.requests, [])

    def test_one_contract_can_still_exceed_equity_at_risk(self):
        fire = self.make(plan=PLAN | {"stop_loss": "62800"})
        fire.start()
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "risk_governor_failed")
        self.assertEqual(self.exchange.requests, [])

    def test_gpt6_wait_is_explicit_no_trade_with_zero_orders(self):
        no_trade = {"direction":"WAIT","contracts":0,
                    "stop_loss":None,"take_profit":None,
                    "thesis":"No price setup with sufficient edge."}
        fire = self.make(plan=no_trade)
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["status"],"rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"],"gpt6_wait_no_trade")
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.exchange.requests,[])

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

    def test_missing_equity_checkpoint_blocks_before_gpt_and_order(self):
        from tradebot.portfolio_equity_guard import PortfolioEquityGuard
        fire = self.make()
        fire.equity_guard = PortfolioEquityGuard(
            self.path.parent / "unseeded-risk.sqlite")
        fire.start()
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "portfolio_equity_limits_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_missing_equity_ledger_does_not_reset_peak_on_controller_restart(self):
        risk = self.path.parent / "fire-equity-risk.sqlite"
        preserved = risk.with_name("preserved-risk.sqlite")
        original = risk.read_bytes()
        risk.rename(preserved)
        fire = self.make()
        self.assertFalse(risk.exists())
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "portfolio_equity_limits_failed")
        self.assertFalse(risk.exists())
        self.assertEqual(preserved.read_bytes(), original)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_corrupt_equity_ledger_does_not_prevent_diagnostic_startup(self):
        risk = self.path.parent / "fire-equity-risk.sqlite"
        risk.write_bytes(b"original corrupt risk evidence")
        fire = self.make()
        self.assertEqual(fire.snapshot()["status"], "idle")
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["reason_code"], "portfolio_equity_limits_failed")
        self.assertEqual(risk.read_bytes(), b"original corrupt risk evidence")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_missing_receipt_blocks_before_paid_model_or_broker_post(self):
        wallet = self.exchange.wallet_balances()
        wallet.pop("equity_read_receipt")
        with patch.object(self.exchange, "wallet_balances", return_value=wallet):
            fire = self.make()
            fire.start()
        self.assertEqual(fire.snapshot()["reason_code"], "portfolio_equity_limits_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

    def test_final_equity_recheck_blocks_loss_after_model_and_budget_checks(self):
        first = self.exchange.wallet_balances()
        second = self.exchange.wallet_balances()
        reduced = self.exchange.wallet_balances()
        reduced["meta"]["net_equity"] = "169"
        reduced["equity_read_receipt"] = receipt_for("169")
        with patch.object(self.exchange, "wallet_balances", side_effect=[first,second,reduced]):
            fire = self.make()
            fire.start()
        self.assertEqual(fire.snapshot()["reason_code"], "portfolio_equity_limits_final_failed")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.exchange.requests, [])

    def test_daily_equity_loss_halts_before_paid_ai(self):
        from unittest.mock import patch
        wallet = self.exchange.wallet_balances()
        reduced = dict(wallet, meta={"net_equity": "169"})
        reduced["equity_read_receipt"] = receipt_for("169")
        with patch.object(self.exchange, "wallet_balances", return_value=reduced):
            fire = self.make()
            fire.start()
            self.assertEqual(fire.snapshot()["reason_code"], "portfolio_equity_limits_failed")
            self.assertEqual(self.calls, [])
            self.assertEqual(self.exchange.requests, [])

    def test_missing_archive_rejects_before_paid_ai_and_broker_order(self):
        fire = self.make()
        fire.archive = None
        self.assertTrue(fire.start()[0])
        self.assertEqual(fire.snapshot()["reason_code"],
                         "historical_data_integrity_failed")
        self.assertFalse(self.calls)
        self.assertFalse(self.exchange.requests)
        self.assertFalse(fire.snapshot()["orders_submitted"])

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

    def test_other_market_unresolved_fire_blocks_new_gpt_decision(self):
        from tradebot.fire_execution import FireTradeStore
        sibling = FireTradeStore(self.path.parent / "fire-xaut.sqlite")
        first = sibling.reserve()
        sibling.update(first, "protected_active")
        fire = self.make()
        fire.start()
        self.assertEqual(fire.snapshot()["status"], "rejected_no_order")
        self.assertEqual(fire.snapshot()["reason_code"], "portfolio_entry_reservation_failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.exchange.requests, [])

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
             "side": "sell", "stop_price": "62950", "size": 1},
            {"id": 12, "product_id": 27, "bracket_order": True,
             "stop_order_type": "take_profit_order", "state": "pending",
             "side": "sell", "stop_price": "63950", "size": 1},
        ]
        self.assertTrue(protective_orders_verified(self.exchange.active_orders,
                       product_id=27, plan=PLAN))
        invalid = list(self.exchange.active_orders)
        invalid[1] = dict(invalid[1], id=11)
        self.assertFalse(protective_orders_verified(invalid, product_id=27, plan=PLAN))
        invalid[1] = dict(invalid[1], stop_price="63800")
        self.assertFalse(protective_orders_verified(invalid, product_id=27, plan=PLAN))

    def test_protection_rejects_undersized_oversized_missing_and_ambiguous_children(self):
        valid = [
            {"id": 11, "product_id": 27, "bracket_order": True,
             "stop_order_type": "stop_loss_order", "state": "pending",
             "side": "sell", "stop_price": "62950", "size": 1},
            {"id": 12, "product_id": 27, "bracket_order": True,
             "stop_order_type": "take_profit_order", "state": "pending",
             "side": "sell", "stop_price": "63950", "size": 1},
        ]
        self.assertTrue(protective_orders_verified(valid, product_id=27, plan=PLAN))
        for field, value in (("size", 0), ("size", 2), ("size", "0.5"),
                             ("size", "NaN"), ("size", True), ("size", None),
                             ("id", True), ("id", {})):
            with self.subTest(field=field, value=value):
                wrong = [dict(v) for v in valid]
                wrong[0][field] = value
                self.assertFalse(protective_orders_verified(
                    wrong, product_id=27, plan=PLAN))
        no_size = [dict(v) for v in valid]
        no_size[1].pop("size")
        self.assertFalse(protective_orders_verified(no_size, product_id=27, plan=PLAN))
        # One matching child of each type is required, not two copies of SL.
        duplicates = [*valid, dict(valid[0], id=13)]
        self.assertFalse(protective_orders_verified(duplicates, product_id=27, plan=PLAN))
        repeated = [*valid, dict(valid[1])]
        self.assertFalse(protective_orders_verified(repeated, product_id=27, plan=PLAN))
        self.assertFalse(protective_orders_verified(
            [*valid, dict(valid[0], id=12)], product_id=27, plan=PLAN))

    def test_extra_conflicting_same_product_order_invalidates_bracket_protection(self):
        valid = [
            {"id": 11, "product_id": 27, "bracket_order": True,
             "stop_order_type": "stop_loss_order", "state": "pending",
             "side": "sell", "stop_price": "62950", "size": 1},
            {"id": 12, "product_id": 27, "bracket_order": True,
             "stop_order_type": "take_profit_order", "state": "pending",
             "side": "sell", "stop_price": "63950", "size": 1},
        ]
        self.assertTrue(protective_orders_verified(valid, product_id=27, plan=PLAN))
        extras = (
            {"id": 13, "product_id": 27, "stop_order_type": "stop_loss_order",
             "bracket_order": True, "state": "pending", "side": "sell",
             "stop_price": "62900", "size": 1},
            {"id": 13, "product_id": 27, "stop_order_type": "take_profit_order",
             "bracket_order": True, "state": "pending", "side": "sell",
             "stop_price": "63950", "size": 2},
            {"id": 13, "product_id": 27, "stop_order_type": "stop_loss_order",
             "bracket_order": False, "state": "pending", "side": "sell",
             "stop_price": "62950", "size": 1},
            {"id": 13, "product_id": 27, "stop_order_type": "take_profit_order",
             "bracket_order": True, "state": "pending", "side": "buy",
             "stop_price": "63950", "size": 1},
            {"id": 13, "product_id": 27, "state": "pending",
             "side": "sell", "size": 1},
            {"id": 13, "product_id": 27, "stop_order_type": "stop_loss_order",
             "bracket_order": True, "state": "cancelled", "side": "sell",
             "stop_price": "62950", "size": 1},
            {"id": "", "product_id": 27, "stop_order_type": "stop_loss_order",
             "bracket_order": True, "state": "pending", "side": "sell",
             "stop_price": "62950", "size": 1},
        )
        for extra in extras:
            with self.subTest(extra=extra):
                self.assertFalse(protective_orders_verified(
                    [*valid, extra], product_id=27, plan=PLAN))
        # This verifier deliberately scopes to the selected product; account-
        # wide pending orders are checked separately by the entry gate.
        other_product = dict(extras[0], product_id=82)
        self.assertTrue(protective_orders_verified(
            [*valid, other_product], product_id=27, plan=PLAN))

    def test_extra_wrong_price_stop_cannot_be_ignored_after_entry_fill(self):
        original = self.exchange._request
        def add_wrong_price_stop(method, path, **kwargs):
            answer = original(method, path, **kwargs)
            if method == "POST" and path == "/v2/orders":
                self.exchange.active_orders.append({
                    "id": 9993, "product_id": 27,
                    "stop_order_type": "stop_loss_order",
                    "bracket_order": True, "side": "sell",
                    "state": "pending", "size": 1,
                    "stop_price": "62700", "product_symbol": "BTCUSD",
                })
            return answer
        self.exchange._request = add_wrong_price_stop
        fire = self.make()
        self.assertTrue(fire.start()[0])
        state = fire.snapshot()
        self.assertEqual(state["status"], "flat_verified")
        self.assertEqual(state["reason_code"], "emergency_flat_verified")
        self.assertFalse(state["protection_verified"])
        self.assertEqual(self.exchange.position, 0)
        self.assertEqual(len(self.exchange.requests), 1)

    def test_undersized_protective_child_is_never_marked_protected(self):
        original = self.exchange._request
        def alter_child(method, path, **kwargs):
            answer = original(method, path, **kwargs)
            if method == "POST" and path == "/v2/orders":
                self.exchange.active_orders[0]["size"] = "0"
            return answer
        self.exchange._request = alter_child
        fire = self.make()
        self.assertTrue(fire.start()[0])
        state = fire.snapshot()
        self.assertEqual(state["status"], "flat_verified")
        self.assertEqual(state["reason_code"], "emergency_flat_verified")
        self.assertFalse(state["protection_verified"])
        self.assertEqual(self.exchange.position, 0)
        self.assertEqual(len(self.exchange.requests), 1)

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
