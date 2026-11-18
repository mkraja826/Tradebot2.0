import unittest
from datetime import datetime, timezone

from tradebot.delta_probe import ProbeError, check_authenticated, check_public
from tradebot.delta import DEMO_API

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class FakeDemo:
    base_url = DEMO_API
    allow_orders = False

    def __init__(self):
        self.calls = []
        self.book_time = int(NOW.timestamp() * 1_000_000)
        self.wallet = {"balances": [{"asset_symbol": "USD",
                                     "available_balance": "10000"}],
                       "meta": {"net_equity": "10000"}}
        self.orders = []
        self.positions = []

    def ticker(self, symbol):
        self.calls.append(("ticker", symbol))
        return {"symbol": symbol, "quotes": {"best_bid": "90000",
                                             "best_ask": "90001"}}

    def btc_orderbook(self, *, depth):
        self.calls.append(("book", depth))
        return {"symbol": "BTCUSD", "last_updated_at": self.book_time,
                "buy": [{"price": "90000", "size": 1}],
                "sell": [{"price": "90001", "size": 2}]}

    def candles(self, *, symbol, resolution, start, end):
        self.calls.append(("candles", symbol, resolution))
        return [{"time": end - 300, "open": "90000", "high": "90010",
                 "low": "89990", "close": "90001", "volume": "10"}]

    def wallet_balances(self):
        self.calls.append(("wallet",))
        return self.wallet

    def open_orders(self):
        self.calls.append(("orders",))
        return self.orders

    def btc_positions(self):
        self.calls.append(("positions",))
        return self.positions


class DeltaProbeTests(unittest.TestCase):
    def setUp(self):
        self.demo = FakeDemo()

    def test_public_never_calls_private_endpoints(self):
        result = check_public(self.demo, now=NOW)
        self.assertEqual(result["public_api"], "passed")
        self.assertFalse(result["orders_submitted"])
        self.assertEqual([x[0] for x in self.demo.calls],
                         ["ticker", "book", "candles"])

    def test_authenticated_reads_only_and_redacts_account_details(self):
        result = check_authenticated(self.demo)
        self.assertEqual(result["authenticated_read"], "passed")
        self.assertEqual([x[0] for x in self.demo.calls],
                         ["wallet", "orders", "positions"])
        self.assertNotIn("10000", str(result))
        self.assertNotIn("USD", str(result))

    def test_bad_public_orderbook_halts(self):
        self.demo.book_time -= 300_000_000
        with self.assertRaises(ProbeError):
            check_public(self.demo, now=NOW)

    def test_bad_wallet_schema_halts(self):
        self.demo.wallet["balances"] = [{"asset_symbol": "USD"}]
        with self.assertRaises(ProbeError):
            check_authenticated(self.demo)

    def test_bad_active_order_identity_halts(self):
        self.demo.orders = [{"product_id": 2, "size": 1}]
        with self.assertRaises(ProbeError):
            check_authenticated(self.demo)

    def test_non_demo_host_refused_before_network(self):
        self.demo.base_url = "https://api.india.delta.exchange"
        with self.assertRaises(ProbeError):
            check_public(self.demo, now=NOW)
        with self.assertRaises(ProbeError):
            check_authenticated(self.demo)
        self.assertEqual(self.demo.calls, [])

    def test_read_only_permission_required(self):
        self.demo.allow_orders = True
        with self.assertRaises(ProbeError):
            check_authenticated(self.demo)


if __name__ == "__main__":
    unittest.main()
