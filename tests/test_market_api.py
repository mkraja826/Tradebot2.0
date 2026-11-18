"""Endpoint contracts use fake responses so CI needs no Delta keys or network."""
import unittest

from tradebot.delta import DEMO_API, DeltaDemo, DeltaError


class StubDelta(DeltaDemo):
    def __init__(self):
        super().__init__(api_key="demo-key", api_secret="demo-secret",
                         allow_orders=False)
        self.calls = []
        self.fake_response = {"success": True, "result": []}

    def _request(self, method, path, *, params=None, payload=None, auth=False):
        self.calls.append((method, path, params, payload, auth))
        return self.fake_response


class MarketAPIContractTests(unittest.TestCase):
    def setUp(self):
        self.exchange = StubDelta()

    def test_btc_tickers_only_and_query_filter(self):
        self.exchange.fake_response = {
            "result": [
                {"symbol": "BTCUSD", "product_id": 1},
                {"symbol": "C-BTC-90000-271126", "product_id": 2},
                {"symbol": "P-BTC-90000-271126", "product_id": 3},
                {"symbol": "ETHUSD", "product_id": 4},
            ]
        }
        result = self.exchange.btc_tickers()
        self.assertEqual(len(result), 3)
        method, path, params, payload, auth = self.exchange.calls[-1]
        self.assertEqual((method, path, auth), ("GET", "/v2/tickers", False))
        self.assertEqual(params["underlying_asset_symbols"], "BTC")
        self.assertIn("call_options", params["contract_types"])

    def test_candle_query_contract(self):
        self.exchange.fake_response = {
            "result": [{"time": 100, "open": 2, "high": 3,
                        "low": 1, "close": 2, "volume": 1}]
        }
        result = self.exchange.candles(symbol="BTCUSD", resolution="5m",
                                       start=100, end=1000)
        self.assertEqual(len(result), 1)
        method, path, params, _, auth = self.exchange.calls[-1]
        self.assertEqual((method, path, auth), ("GET", "/v2/history/candles", False))
        self.assertEqual(params, {"symbol": "BTCUSD", "resolution": "5m",
                                  "start": 100, "end": 1000})

    def test_non_btc_candles_disallowed(self):
        with self.assertRaises(ValueError):
            self.exchange.candles(symbol="ETHUSD", resolution="5m",
                                  start=100, end=1000)
        self.assertEqual(self.exchange.calls, [])

    def test_missing_candles_fail(self):
        with self.assertRaises(DeltaError):
            self.exchange.candles(start=100, end=200)

    def test_order_book_contract(self):
        self.exchange.fake_response = {
            "result": {"symbol": "BTCUSD", "buy": [], "sell": []}
        }
        result = self.exchange.btc_orderbook(depth=20)
        self.assertEqual(result["symbol"], "BTCUSD")
        method, path, params, _, auth = self.exchange.calls[-1]
        self.assertEqual((method, path, auth), ("GET",
                          "/v2/l2orderbook/BTCUSD", False))
        self.assertEqual(params["depth"], 20)

    def test_orderbook_depth_bound(self):
        with self.assertRaises(ValueError):
            self.exchange.btc_orderbook(depth=0)
        with self.assertRaises(ValueError):
            self.exchange.btc_orderbook(depth=101)

    def test_wallet_is_signed_read_only(self):
        self.exchange.fake_response = {
            "result": [{"asset_symbol": "USD", "available_balance": "100"}],
            "meta": {"net_equity": "100"}
        }
        wallet = self.exchange.wallet_balances()
        self.assertEqual(wallet["meta"]["net_equity"], "100")
        method, path, _, _, auth = self.exchange.calls[-1]
        self.assertEqual((method, path, auth),
                         ("GET", "/v2/wallet/balances", True))

    def test_wallet_malformed_result_fails_closed(self):
        self.exchange.fake_response = {"result": None}
        with self.assertRaises(DeltaError):
            self.exchange.wallet_balances()

    def test_demo_host_cannot_be_reconfigured(self):
        self.assertEqual(self.exchange.base_url, DEMO_API)
        with self.assertRaises(AttributeError):
            self.exchange.base_url = "https://api.india.delta.exchange"


if __name__ == "__main__":
    unittest.main()
