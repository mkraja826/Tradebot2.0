from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tradebot.delta import DeltaError
from tradebot.fire_execution import FireDemoController
from tradebot.fire_market import FireMarket
from tradebot.fire_watchdog import watchdog_tick
from tradebot.trade_memory import TradeMemory
from test_fire_execution import seed_demo_equity
from equity_fixtures import receipt_for


class DemoAccount(FireMarket):
    """Both markets share the order list, just as on the demo exchange."""
    def __init__(self):
        super().__init__("XAUTUSD", allow_orders=True)
        self.btc_order = {"id": 1, "product_id": 27}
        self.orders = []
        self.gold_size = 0
        self.posts = []
        self.parent = {}

    def candles(self, *, symbol, resolution, start, end):
        assert symbol == self.symbol
        return []

    def ticker(self, symbol):
        assert symbol == "XAUTUSD"
        return {"symbol": symbol, "product_id": 82, "contract_type": "perpetual_futures",
                "mark_price": "3800", "timestamp": datetime.now(timezone.utc).timestamp(),
                "quotes": {"best_bid":"3799", "best_ask":"3801"}}

    def _request(self, method, path, *, params=None, payload=None, auth=False):
        if method == "GET" and path == "/v2/products/BTCUSD":
            return {"result": {"symbol": "BTCUSD", "id": 27,
                               "contract_type": "perpetual_futures"}}
        if method == "GET" and path == "/v2/products/XAUTUSD":
            return {"result": {"symbol": self.symbol, "id": 82, "contract_type": "perpetual_futures",
                               "settling_asset": {"symbol": "USD"}, "notional_type": "vanilla",
                               "initial_margin": "0.5", "contract_value": "0.001",
                               "tick_size": "0.01", "taker_commission_rate": "0.0005"}}
        if method == "GET" and path == "/v2/products/82/orders/leverage":
            return {"result": {"leverage": 5, "product_id": 82}}
        if method == "GET" and path == "/v2/wallet/balances":
            return {"result": [{"asset_symbol": "USD", "available_balance": "100"}],
                    "_wallet_read_receipt": receipt_for("100"),
                    "meta": {"net_equity": "100"}}
        if method == "GET" and path == "/v2/positions":
            assert params in ({"product_id":82}, {"product_id":27})
            if params["product_id"] == 27:
                return {"result": {"product_id": 27, "entry_price":"0","size":0}}
            return {"result":{"entry_price":"3800","size": self.gold_size}}
        if method == "GET" and path == "/v2/orders":
            return {"result": self.orders[:], "meta": {"after": None}}
        if method == "GET" and path == "/v2/profile":
            return {"result": {"margin_mode": "isolated"}}
        if method == "GET" and path == "/v2/positions/margined":
            assert params in (None, {"product_ids": "82"})
            return {"result": ([{"product_id": 82, "size": self.gold_size,
                                 "margin_mode": "isolated", "entry_price": "3800",
                                 "liquidation_price": "3500"}]
                                if self.gold_size else [])}
        if method == "GET" and path.startswith("/v2/orders/client_order_id/"):
            return {"result":self.parent}
        assert payload["product_id"] == 82
        if method == "DELETE":
            self.orders = [o for o in self.orders if o["product_id"] != 82]
            return {"success":True}
        assert method == "POST" and path == "/v2/orders"
        self.posts.append(payload)
        if payload["reduce_only"]:
            self.gold_size = 0
        else:
            self.gold_size = payload["size"]
            self.parent = dict(payload,id=3,state="closed",unfilled_size=0)
            self.orders.extend({"id":i, "product_id":82, "side":"sell", "state":"pending",
                                "bracket_order":True, "stop_order_type":kind, "stop_price":price, "size":1}
                               for i,kind,price in [(4,"stop_loss_order","3700"),(5,"take_profit_order","4000")])
        return {"result":self.parent}


class MarketTest(unittest.TestCase):
    def test_product_scoped_positions_preserve_short_and_reject_conflicting_id(self):
        market = DemoAccount()
        market.gold_size = -2
        self.assertEqual(market.positions(), [{"product_id": 82, "size": -2, "entry_price": "3800"}])
        with patch.object(market, "_request", return_value={"result": {"product_id": 27, "size": 1}}):
            with self.assertRaises(DeltaError):
                market.positions()

    def test_gold_book_is_checked_at_receipt_and_ticker_is_read_once(self):
        market = FireMarket("XAUTUSD")
        start = datetime.now(timezone.utc)
        received = start + timedelta(seconds=15)
        ticker = {"product_id": 82, "symbol": "XAUTUSD", "contract_type": "perpetual_futures",
                  "product_trading_status": "operational", "timestamp": start.timestamp()}
        book = {"symbol": "XAUTUSD", "last_updated_at": received.timestamp(),
                "buy": [{"price": "3799"}], "sell": [{"price": "3801"}]}
        candles = [dict(time=int(start.timestamp()) - i * 300, open=3800, high=3800,
                        low=3800, close=3800, volume=1) for i in range(13)]
        with (patch("tradebot.fire_market.datetime") as clock,
              patch.object(market, "ticker", return_value=ticker) as fetch,
              patch.object(market, "_request", return_value={"result": book}),
              patch.object(market, "candles", return_value=candles),
              patch.object(market, "wallet_balances", return_value={"balances": [], "meta": {}}),
              patch.object(market, "positions", return_value=[])):
            clock.now.side_effect = [start, received]
            self.assertEqual(market.snapshot()["core"]["symbol"], "XAUTUSD")
            self.assertEqual(market.product_id, 82)
            fetch.assert_called_once_with("XAUTUSD")

    def test_emergency_reduce_only_precedes_protective_cancellation(self):
        broker = DemoAccount()
        broker.gold_size = 1
        broker.orders = [
            {"id": 8, "product_id": 82, "state": "pending", "stop_order_type": "stop_loss_order"},
            {"id": 9, "product_id": 82, "state": "pending", "stop_order_type": "take_profit_order"},
        ]
        orig = broker._request
        observations = []
        def track(method, path, **kwargs):
            if method == "POST" and path == "/v2/orders" and kwargs["payload"]["reduce_only"]:
                self.assertTrue(broker.orders, "Bracket already cancelled before reduce-only exit")
                observations.append("close_first")
            if method == "DELETE":
                self.assertEqual(broker.gold_size, 0, "Cancelled while position still open")
                observations.append("cancel_after_flat")
            return orig(method, path, **kwargs)
        broker._request = track
        broker.close_exposure(lambda _: None)
        self.assertEqual(observations, ["close_first", "cancel_after_flat"])
        self.assertEqual(broker.gold_size, 0)
        self.assertEqual(broker.orders, [])

    def test_failed_reduce_only_preserves_protective_orders(self):
        broker = DemoAccount()
        broker.gold_size = -1
        stop = {"id": 8, "product_id": 82, "state": "pending", "stop_order_type": "stop_loss_order"}
        broker.orders = [stop]
        orig = broker._request
        def reject(method, path, **kwargs):
            if method == "POST" and path == "/v2/orders" and kwargs["payload"]["reduce_only"]:
                raise DeltaError("Ambiguous reduce-only exit response")
            return orig(method, path, **kwargs)
        broker._request = reject
        with self.assertRaises(DeltaError):
            broker.close_exposure(lambda _: None)
        self.assertEqual(broker.gold_size, -1)
        self.assertEqual(broker.orders, [stop])

    def test_unconfirmed_close_never_cancels_brackets_or_reposts(self):
        broker = DemoAccount()
        broker.gold_size = 1
        broker.orders = [{"id": 8, "product_id": 82, "state": "pending",
                          "stop_order_type": "stop_loss_order"}]
        orig = broker._request
        attempts = []
        def delayed(method, path, **kwargs):
            if method == "POST" and path == "/v2/orders" and kwargs["payload"]["reduce_only"]:
                attempts.append("post")
                return {"result": {"id": 42}}
            if method == "DELETE":
                self.fail("Unconfirmed exit cancelled protection")
            return orig(method, path, **kwargs)
        broker._request = delayed
        with self.assertRaisesRegex(DeltaError, "protective orders preserved"):
            broker.close_exposure(lambda _: None)
        self.assertEqual(attempts, ["post"])
        self.assertEqual(broker.gold_size, 1)
        self.assertEqual(len(broker.orders), 1)

    def test_gold_entry_and_emergency_closeout_leave_bitcoin_order_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = DemoAccount()
            seed_demo_equity(Path(tmp) / "fire-xaut.sqlite", "100")
            def snapshot(symbol):
                return {"environment":"delta-india-demo","position_contracts":0,
                        "collected_at":datetime.now(timezone.utc).isoformat(),
                        "core":{"best_bid":"3799","best_ask":"3801","ticker":broker.ticker(symbol)}}
            def decide(routes, loader):
                self.assertEqual(loader()["core"]["ticker"]["symbol"], "XAUTUSD")
                self.assertEqual(loader()["fire_execution_scope"]["max_contracts_per_entry"], 1)
                return {"results":{"fire":{"decision":{"direction":"LONG","contracts":1,"leverage":5,
                                                      "stop_loss":"3700","take_profit":"4000"}}}}
            desk = FireDemoController(Path(tmp)/"fire-xaut.sqlite",enabled=True,symbol="XAUTUSD",
                                      exchange_factory=lambda:broker,snapshot_loader=snapshot,probe=decide,
                                      spawn=lambda job:job(),pause=lambda _:None)
            # The mandatory history gate must be configured even in mocks.
            class ValidArchive:
                def levels(self, symbol, at, price):
                    return {"periods": {
                        key: {"quality_status": "provisionally_valid"}
                        for key in ("day", "previous_day", "week", "previous_week",
                                    "month", "previous_month")
                    }}
            desk.archive = ValidArchive()
            self.assertTrue(desk.start()[0])
            self.assertEqual(desk.snapshot()["status"],"protected_active")
            self.assertEqual(watchdog_tick(broker,desk.store)["status"], "protected_active")
            # A BTC manual order appearing AFTER Gold's verified entry must
            # not be cancelled during Gold's emergency closeout.
            broker.orders.insert(0, broker.btc_order)
            broker.orders.pop()
            self.assertEqual(watchdog_tick(broker,desk.store)["status"],"emergency_flat_verified")
            self.assertEqual(broker.orders,[broker.btc_order])
            self.assertEqual([p["reduce_only"] for p in broker.posts],[False,True])

    def test_existing_btc_manual_order_prevents_gold_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = DemoAccount()
            broker.orders = [broker.btc_order]
            seed_demo_equity(Path(tmp) / "fire-xaut.sqlite", "100")
            called = []
            def snapshot(symbol):
                return {"environment":"delta-india-demo", "position_contracts":0,
                        "collected_at":datetime.now(timezone.utc).isoformat(),
                        "core":{"best_bid":"3799","best_ask":"3801","ticker":broker.ticker(symbol)}}
            def decide(routes, loader):
                called.append(True)
                return {"results":{"fire":{"decision":{"direction":"LONG",
                      "contracts":1,"leverage":5,"stop_loss":"3700","take_profit":"4000"}}}}
            desk = FireDemoController(Path(tmp)/"fire-xaut.sqlite", enabled=True,
                                      symbol="XAUTUSD", exchange_factory=lambda: broker,
                                      snapshot_loader=snapshot, probe=decide,
                                      spawn=lambda callback:callback(), pause=lambda _:None)
            desk.start()
            self.assertEqual(desk.snapshot()["reason_code"], "account_exposure_preflight_failed")
            self.assertEqual(called, [])
            self.assertEqual(broker.posts, [])

    def test_independent_kimi_position_tracking(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = TradeMemory(Path(tmp)/"learn.sqlite")
            for symbol,size in (("BTCUSD",1),("XAUTUSD",-2)):
                memory.save_watch_state(symbol=symbol,trade_id=symbol,active=True,size=size,
                                        mark=1,observed_at="2026-11-19")
            self.assertEqual(memory.watch_state()["last_size"],"1")
            self.assertEqual(memory.watch_state("XAUTUSD")["last_size"],"-2")
