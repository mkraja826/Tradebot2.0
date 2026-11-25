import unittest
from recover_trading.engine import Engine, Journal, OrderIntent
from recover_trading.broker import DEMO_API, signature
import hashlib
import hmac


class Broker:
    def __init__(self):
        self.calls = []
        self.fail = False

    def ticker(self, symbol):
        return {"symbol": symbol, "mark_price": "100"}

    def submit(self, intent, client_id):
        self.calls.append((intent, client_id))
        if self.fail:
            raise TimeoutError()
        return {"id": 1}

    def order(self, client_id):
        return {"id": 2}


class Strategy:
    def __init__(self, intent):
        self.intent = intent

    def decide(self, symbol, ticker):
        return self.intent


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.journal = Journal(":memory:")
        self.addCleanup(self.journal.close)
        self.broker = Broker()

    def test_strategy_quantity_is_unchanged_and_no_cooldown(self):
        intent = OrderIntent(5, "buy", 900)
        engine = Engine(self.broker, Strategy(intent), self.journal)
        engine.tick("EXAMPLE")
        engine.tick("EXAMPLE")
        self.assertEqual([v[0] for v in self.broker.calls], [intent, intent])
        self.assertNotEqual(self.broker.calls[0][1], self.broker.calls[1][1])

    def test_no_trade_is_strategy_choice(self):
        self.assertIsNone(Engine(self.broker, Strategy(None), self.journal).tick("EXAMPLE"))
        self.assertEqual(self.broker.calls, [])

    def test_timeout_is_reconciled_without_reposting(self):
        self.broker.fail = True
        engine = Engine(self.broker, Strategy(OrderIntent(5, "sell", 3)), self.journal)
        with self.assertRaises(TimeoutError):
            engine.tick("EXAMPLE")
        self.assertEqual(len(self.journal.unresolved()), 1)
        engine.reconcile()
        self.assertEqual(self.journal.unresolved(), [])
        self.assertEqual(len(self.broker.calls), 1)

    def test_demo_endpoint_and_signature(self):
        self.assertEqual(DEMO_API, "https://cdn-ind.testnet.deltaex.org")
        expected = hmac.new(b"secret", b"GET123/v2/orders?a=1", hashlib.sha256).hexdigest()
        self.assertEqual(signature("secret", "GET", "123", "/v2/orders", "?a=1"), expected)


if __name__ == "__main__":
    unittest.main()
