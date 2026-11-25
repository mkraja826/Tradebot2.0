import tempfile
import threading
import unittest
from recover_trading.service import MarketService, credentials
from test_recover_execution import Fake
from test_recover_decision import report

class Provider:
    def __init__(self):
        self.calls = 0
    def propose(self, model, context):
        self.calls += 1
        return {"symbol": context["symbol"], "action": "trade", "side": "sell",
                "size": 90, "leverage": 20, "capital_allocation": 45,
                "entry_reference": 100, "stop_loss": 105, "take_profit": 95,
                "reason": "fixture"}

def scan(path, *, symbols, include_context):
    return {"markets": {s: report(s) for s in symbols}}

class ServiceTests(unittest.TestCase):
    def test_preview_no_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            service = MarketService("BTCUSD", directory, scan=scan, output=events.append)
            service.run(threading.Event(), 1, once=True)
            self.assertEqual(events[0]["status"], "preview")
            self.assertEqual(events[0]["ai_calls"], 0)
    def test_restart_does_not_repeat_and_markets_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            for symbol in ("BTCUSD", "XAUTUSD"):
                events = []
                provider, broker = Provider(), Fake()
                for _ in range(2):
                    service = MarketService(symbol, directory, model="fixture",
                                            provider=provider, broker=broker, scan=scan,
                                            output=events.append)
                    service.run(threading.Event(), 1, once=True)
                self.assertEqual(events[0]["execution_status"], "acknowledged")
                self.assertEqual(events[1]["status"], "already_evaluated")
                self.assertEqual(provider.calls, 1)
                self.assertEqual(sum(m == "POST" and p == "/v2/orders" for m,p,k in broker.calls), 1)
    def test_cycle_exception_does_not_terminate_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            events, stop = [], threading.Event()
            def output(event):
                events.append(event)
                if len(events) == 2:
                    stop.set()
            def flaky(*args, **kwargs):
                if not events:
                    raise OSError()
                return scan(*args, **kwargs)
            service = MarketService("BTCUSD", directory, scan=flaky, output=output)
            service.run(stop, 0.001)
            self.assertEqual([e["status"] for e in events], ["cycle_error", "preview"])
    def test_credentials_are_market_specific(self):
        env = {"RECOVER_BTC_DEMO_KEY":"btc", "RECOVER_BTC_DEMO_SECRET":"secret"}
        self.assertEqual(credentials("BTCUSD",env), ("btc","secret"))
        with self.assertRaises(ValueError):
            credentials("XAUTUSD",env)
