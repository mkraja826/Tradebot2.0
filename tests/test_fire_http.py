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
from tradebot.chart_desk import ChartDesk
from tradebot.fire_execution import FireDemoController


from test_fire_execution import FakeDemo, snapshot, seed_demo_equity


class FireHttpTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.exchange = FakeDemo()
        seed_demo_equity(root / "fire-ops.sqlite", "173.81")
        self.model_calls = []
        def gpt6(routes, loader):
            self.model_calls.append(routes)
            self.assertIn("indicators", loader())
            return {"results": {"fire": {"decision": {
                "direction": "LONG", "contracts": 1,
                "stop_loss": "62950", "take_profit": "63950",
            }}}}
        trade = FireDemoController(
            root / "fire-ops.sqlite", enabled=True,
            exchange_factory=lambda: self.exchange,
            snapshot_loader=snapshot, probe=gpt6,
            spawn=lambda run: run(), pause=lambda _: None,
        )
        class State:
            fire_trade = trade
            chart_desk = ChartDesk(self.exchange, {"BTCUSD":trade.store})
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
        self.assertEqual(len(self.exchange.requests), 0)
        self.assertEqual(self.model_calls, [])

    def test_plugin_retry_and_review_use_exact_fire(self):
        fire_id = "1234567890abcdef" * 2
        path = "/api/plugin/fire/BTCUSD/" + fire_id
        for reason in ("accepted", "existing_receipt"):
            with self.post(path, origin=self.origin, action="fire-execute") as response:
                result = json.load(response)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["receipt"]["press"], fire_id)
                self.assertEqual(result["receipt"]["status"], "protected_active")
        self.assertEqual(len(self.model_calls), 1)
        self.assertEqual(len(self.exchange.requests), 1)
        with urlopen(self.origin + "/api/plugin/review/BTCUSD/" + fire_id) as response:
            result = json.load(response)
            self.assertEqual(result["id"], fire_id)
            self.assertIn("scorecard", result)
            self.assertEqual(result["direction"], "LONG")

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
            self.assertEqual(state["stop_loss"], "62950")
            self.assertEqual(state["take_profit"], "63950")
        self.assertEqual(len(self.model_calls), 1)
        self.assertEqual(len(self.exchange.requests), 1)
        with self.assertRaises(HTTPError) as duplicate:
            self.post(origin=self.origin, action="fire-execute")
        self.assertEqual(duplicate.exception.code, 409)
        self.assertEqual(len(self.exchange.requests), 1)


if __name__ == "__main__":
    unittest.main()
