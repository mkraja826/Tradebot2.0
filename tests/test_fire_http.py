"""Private Demo FIRE HTTP route requires intentional same-origin action."""
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
from threading import Thread
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tradebot.dashboard import create_handler
from tradebot.delta import DEMO_API
from tradebot.fire_execution import FireDemoController


class FakeExchange:
    base_url = DEMO_API
    allow_orders = True

    def __init__(self):
        self.posts = 0
        self.position = 0
        self.children = []
        self.parent = None

    def ticker(self, symbol):
        return {"symbol": "BTCUSD", "product_id": 27,
                "mark_price": "63214.25",
                "timestamp": int(datetime.now(timezone.utc).timestamp()),
                "quotes": {"best_bid": "63214", "best_ask": "63214.5"}}

    def btc_positions(self):
        return [{"product_id": 27, "size": str(self.position)}] if self.position else []

    def open_orders(self):
        return self.children

    def _request(self, method, path, *, auth, payload):
        self.posts += 1
        self.position = 1
        self.parent = {"id": 47, "product_id": 27,
                       "client_order_id": payload["client_order_id"],
                       "state": "closed", "unfilled_size": 0}
        self.children = [{
            "id": i, "product_id": 27, "side": "sell", "state": "pending",
            "stop_order_type": typ, "bracket_order": True, "stop_price": value,
        } for i, typ, value in [
            (50, "stop_loss_order", payload["bracket_stop_loss_price"]),
            (51, "take_profit_order", payload["bracket_take_profit_price"]),
        ]]
        return {"result": self.parent}

    def order_by_client_id(self, press):
        return self.parent


def snapshot():
    return {
        "environment": "delta-india-demo",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "position_contracts": 0,
        "core": {
            "best_bid": "63214", "best_ask": "63214.5",
            "ticker": {"product_id": 27, "symbol": "BTCUSD",
                       "contract_type": "perpetual_futures"}
        },
    }


class FireHttpTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.exchange = FakeExchange()
        self.model_calls = []
        def gpt6(routes, loader):
            self.model_calls.append(routes)
            loader()
            return {"results": {"fire": {"decision": {
                "direction": "LONG", "contracts": 1,
                "stop_loss": "62800", "take_profit": "63750",
            }}}}
        trade = FireDemoController(
            root / "fire-ops.sqlite", enabled=True,
            exchange_factory=lambda: self.exchange,
            snapshot_loader=snapshot, probe=gpt6,
            spawn=lambda run: run(), pause=lambda _: None,
        )
        class State:
            fire_trade = trade
            def snapshot(self):
                return {"dashboard_mode": "read_only"}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(State()))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.origin = "http://127.0.0.1:" + str(self.server.server_port)

    def post(self, path="/api/fire", *, origin=None, action=None, data=b""):
        headers = {}
        if origin is not None:
            headers["Origin"] = origin
        if action is not None:
            headers["X-Tradebot-Action"] = action
        return urlopen(Request(
            self.origin + path, headers=headers, data=data, method="POST"
        ))

    def test_csrf_writes_and_unsupported_routes_are_blocked(self):
        for args, expected in [
            ({}, 403),
            ({"origin": "https://evil.example",
              "action": "fire-execute"}, 403),
            ({"origin": self.origin, "action": "fire-preview"}, 403),
            ({"origin": self.origin, "action": "fire-execute",
              "data": b'{"size":99}'}, 403),
            ({"path": "/api/market", "origin": self.origin,
              "action": "fire-execute"}, 405),
        ]:
            with self.subTest(args=args), self.assertRaises(HTTPError) as error:
                self.post(**args)
            self.assertEqual(error.exception.code, expected)
        self.assertEqual(self.exchange.posts, 0)
        self.assertEqual(self.model_calls, [])

    def test_single_authorized_click_executes_one_demo_bracket(self):
        with urlopen(self.origin + "/api/fire") as result:
            self.assertEqual(result.status, 200)
            self.assertEqual(json.load(result)["status"], "idle")
        with self.post(origin=self.origin, action="fire-execute") as result:
            self.assertEqual(result.status, 202)
            self.assertTrue(json.load(result)["execution_enabled"])
        with urlopen(self.origin + "/api/fire") as result:
            state = json.load(result)
            self.assertEqual(state["status"], "protected_active")
            self.assertTrue(state["protection_verified"])
            self.assertEqual(state["direction"], "LONG")
            self.assertEqual(state["stop_loss"], "62800")
            self.assertEqual(state["take_profit"], "63750")
        self.assertEqual(len(self.model_calls), 1)
        self.assertEqual(self.exchange.posts, 1)
        with self.assertRaises(HTTPError) as duplicate:
            self.post(origin=self.origin, action="fire-execute")
        self.assertEqual(duplicate.exception.code, 409)
        self.assertEqual(self.exchange.posts, 1)


if __name__ == "__main__":
    unittest.main()
