"""Offline commissioning tests: manual paid calls only; no exchange orders."""
from http.server import ThreadingHTTPServer
import json
from threading import Event, Thread
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tradebot.dashboard import create_handler
from tradebot.fire_dashboard import FirePreviewController
from tradebot.fire_probe import ROLES


def fake_report(routes, snapshot_loader):
    snapshot_loader()
    return {
        "collected_at": "2026-11-18T10:00:00Z",
        "snapshot_sha256": "f" * 64,
        "results": {
            "fire": {
                "model": routes["fire"], "latency_ms": 100,
                "decision": {
                    "direction": "LONG", "contracts": 1,
                    "stop_loss": "98000", "take_profit": "102000",
                },
                "usage": {"total_tokens": 410},
                "request_id": "private-id",
            },
            "paper": {
                "model": routes["paper"], "latency_ms": 112,
                "error": "upstream secret provider content",
            },
        },
    }


class FirePreviewTests(unittest.TestCase):
    def test_only_one_user_triggered_probe_and_cooldown(self):
        clock = [1000.0]
        invocations = []
        finished = Event()

        def probe(routes, loader):
            invocations.append(dict(routes))
            try:
                return fake_report(routes, loader)
            finally:
                finished.set()

        controller = FirePreviewController(
            probe=probe, snapshot_loader=lambda: None,
            clock=lambda: clock[0])
        self.assertEqual(invocations, [])
        self.assertEqual(controller.snapshot()["status"], "idle")
        ok, reason = controller.start()
        self.assertTrue(ok)
        self.assertEqual(reason, "started")
        self.assertTrue(finished.wait(3))
        for _ in range(100):
            if controller.snapshot()["status"] == "completed":
                break
            time.sleep(.005)
        status = controller.snapshot()
        self.assertEqual(status["status"], "completed")
        self.assertFalse(status["orders_submitted"])
        self.assertEqual(status["result"]["results"]["fire"]["decision"]["direction"], "LONG")
        self.assertIn("error", status["result"]["results"]["paper"])
        self.assertNotIn("upstream secret", json.dumps(status))
        self.assertNotIn("private-id", json.dumps(status))
        self.assertEqual(len(invocations), 1)
        allowed, reason = controller.start()
        self.assertFalse(allowed)
        self.assertEqual(reason, "cooldown_active")
        self.assertEqual(len(invocations), 1)
        clock[0] += 301
        allowed, reason = controller.start()
        self.assertTrue(allowed)
        self.assertEqual(reason, "started")

    def test_failure_is_sanitized_and_keeps_read_only_status(self):
        finished = Event()
        def bad_probe(*args):
            try:
                raise RuntimeError("secret-provider-raw-content")
            finally:
                finished.set()
        controller = FirePreviewController(probe=bad_probe, snapshot_loader=lambda: None)
        controller.start()
        self.assertTrue(finished.wait(3))
        for _ in range(100):
            if controller.snapshot()["status"] == "failed":
                break
            time.sleep(.005)
        payload = json.dumps(controller.snapshot())
        self.assertIn("failed", payload)
        self.assertNotIn("secret-provider-raw-content", payload)
        self.assertIn('"orders_submitted": false', payload)

    def test_http_origin_and_custom_header_are_required(self):
        called = []
        finished = Event()
        def probe(routes, loader):
            called.append(1)
            try:
                return fake_report(routes, loader)
            finally:
                finished.set()

        class Stub:
            fire_preview = FirePreviewController(probe=probe, snapshot_loader=lambda: None)
            def snapshot(self):
                return {"dashboard_mode": "read_only"}

        server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(Stub()))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        origin = "http://127.0.0.1:" + str(port)
        url = origin + "/api/fire-preview"

        def post(headers=None, data=b""):
            return urlopen(Request(url, data=data, headers=headers or {}, method="POST"))

        with self.assertRaises(HTTPError) as missing_origin:
            post({"X-Tradebot-Action": "fire-preview"})
        self.assertEqual(missing_origin.exception.code, 403)

        with self.assertRaises(HTTPError) as cross_site:
            post({"X-Tradebot-Action": "fire-preview",
                  "Origin": "https://attacker.test"})
        self.assertEqual(cross_site.exception.code, 403)

        with self.assertRaises(HTTPError) as header_missing:
            post({"Origin": origin})
        self.assertEqual(header_missing.exception.code, 403)

        with self.assertRaises(HTTPError) as bad_body:
            post({"Origin": origin,
                  "X-Tradebot-Action": "fire-preview"}, b'{"execute":true}')
        self.assertEqual(bad_body.exception.code, 403)
        self.assertEqual(called, [])

        with post({"Origin": origin,
                   "X-Tradebot-Action": "fire-preview"}) as reply:
            self.assertEqual(reply.status, 202)
            self.assertFalse(json.load(reply)["orders_submitted"])
        self.assertTrue(finished.wait(3))
        with urlopen(url) as reply:
            self.assertEqual(reply.status, 200)
            self.assertEqual(json.load(reply)["mode"], "read_only_research")
        with self.assertRaises(HTTPError) as retry:
            post({"Origin": origin, "X-Tradebot-Action": "fire-preview"})
        self.assertEqual(retry.exception.code, 429)
        self.assertEqual(len(called), 1)

        with self.assertRaises(HTTPError) as no_order_route:
            post({"Origin": origin, "X-Tradebot-Action": "fire-preview",
                  "Host": "127.0.0.1:" + str(port)}, b"{}")
        self.assertEqual(no_order_route.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
