"""Offline tests for explicit 24x7 order authorization and AI instructions."""
import io
import json
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from tradebot import cli
from tradebot.ai import AIPlanner


class Reply(io.BytesIO):
    def __init__(self, data):
        super().__init__(json.dumps(data).encode("utf-8"))
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Transport:
    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout):
        payload = json.loads(request.data)
        self.requests.append(payload)
        return Reply({
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "strategy": "WAIT", "rationale": "Risk versus reward poor",
                    "orders": [],
                })},
            }],
            "usage": {"total_tokens": 100},
        })


class Crypto24x7AuthorizationTests(unittest.TestCase):
    def test_24x7_demo_requires_separate_confirmation(self):
        args = ["tradebot", "run", "--mode", "demo", "--schedule",
                "crypto-24x7", "--demo-execute"]
        env = {
            "ENABLE_DEMO_ORDERS": "true",
            "DELTA_DEMO_API_KEY": "fake-demo-key",
            "DELTA_DEMO_API_SECRET": "fake-demo-secret",
            "ALLOW_CRYPTO_24X7_DEMO": "false",
        }
        with patch("sys.argv", args), patch.dict(os.environ, env, clear=True):
            with redirect_stderr(io.StringIO()) as captured:
                with self.assertRaises(SystemExit) as ex:
                    cli.main()
        self.assertEqual(ex.exception.code, 2)
        self.assertIn("separate ALLOW_CRYPTO_24X7_DEMO=true", captured.getvalue())

    def test_new_crypto_prompt_does_not_require_nyse_end_close(self):
        transport = Transport()
        planner = AIPlanner(api_key="dummy-test-key", transport=transport)
        market = {
            "environment": "delta-india-demo",
            "session_phase": "trading",
            "trading_schedule": "crypto-24x7",
            "max_hold_seconds": 900,
            "core": {"best_bid": "90000", "best_ask": "90001", "ticker": {}},
            "technical": {},
            "options": [],
            "futures": [],
        }
        products = [{
            "id": 1, "symbol": "BTCUSD", "contract_type": "perpetual_futures",
            "state": "live",
        }]
        plan = planner.propose(market, products)
        self.assertEqual(plan.orders, ())
        instructions = transport.requests[0]["messages"][0]["content"]
        self.assertIn("around the clock", instructions)
        self.assertIn("900 seconds", instructions)
        self.assertNotIn("positions must be closed before the end of the US stock session",
                         instructions)
        self.assertNotIn("dummy-test-key", json.dumps(transport.requests[0]))


if __name__ == "__main__":
    unittest.main()
