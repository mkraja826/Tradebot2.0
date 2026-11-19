from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from tradebot.fire_execution import FireDemoController
from tradebot.fire_market import FireMarket
from tradebot.fire_watchdog import watchdog_tick
from tradebot.trade_memory import TradeMemory


class DemoAccount(FireMarket):
    """Both markets share the order list, just as on the demo exchange."""
    def __init__(self):
        super().__init__("XAUTUSD", allow_orders=True)
        self.btc_order = {"id": 1, "product_id": 27}
        self.orders = [self.btc_order]
        self.gold_size = 0
        self.posts = []
        self.parent = {}

    def ticker(self, symbol):
        assert symbol == "XAUTUSD"
        return {"symbol": symbol, "product_id": 82, "contract_type": "perpetual_futures",
                "mark_price": "3800", "timestamp": datetime.now(timezone.utc).timestamp(),
                "quotes": {"best_bid":"3799", "best_ask":"3801"}}

    def _request(self, method, path, *, params=None, payload=None, auth=False):
        if method == "GET" and path == "/v2/positions":
            assert params == {"product_id":82}
            return {"result":{"product_id":82,"size": self.gold_size}}
        if method == "GET" and path == "/v2/orders":
            return {"result":self.orders[:]}
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
                                "bracket_order":True, "stop_order_type":kind, "stop_price":price}
                               for i,kind,price in [(4,"stop_loss_order","3700"),(5,"take_profit_order","3900")])
        return {"result":self.parent}


class MarketTest(unittest.TestCase):
    def test_gold_entry_and_emergency_closeout_leave_bitcoin_order_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = DemoAccount()
            def snapshot(symbol):
                return {"environment":"delta-india-demo","position_contracts":0,
                        "collected_at":datetime.now(timezone.utc).isoformat(),
                        "core":{"best_bid":"3799","best_ask":"3801","ticker":broker.ticker(symbol)}}
            def decide(routes, loader):
                self.assertEqual(loader()["core"]["ticker"]["symbol"], "XAUTUSD")
                return {"results":{"fire":{"decision":{"direction":"LONG","contracts":1,
                                                      "stop_loss":"3700","take_profit":"3900"}}}}
            desk = FireDemoController(Path(tmp)/"fire-xaut.sqlite",enabled=True,symbol="XAUTUSD",
                                      exchange_factory=lambda:broker,snapshot_loader=snapshot,probe=decide,
                                      spawn=lambda job:job(),pause=lambda _:None)
            self.assertTrue(desk.start()[0])
            self.assertEqual(desk.snapshot()["status"],"protected_active")
            self.assertEqual(watchdog_tick(broker,desk.store)["status"], "protected_active")
            broker.orders.pop()
            self.assertEqual(watchdog_tick(broker,desk.store)["status"],"emergency_flat_verified")
            self.assertEqual(broker.orders,[broker.btc_order])
            self.assertEqual([p["reduce_only"] for p in broker.posts],[False,True])

    def test_independent_kimi_position_tracking(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = TradeMemory(Path(tmp)/"learn.sqlite")
            for symbol,size in (("BTCUSD",1),("XAUTUSD",-2)):
                memory.save_watch_state(symbol=symbol,trade_id=symbol,active=True,size=size,
                                        mark=1,observed_at="2026-11-19")
            self.assertEqual(memory.watch_state()["last_size"],"1")
            self.assertEqual(memory.watch_state("XAUTUSD")["last_size"],"-2")
