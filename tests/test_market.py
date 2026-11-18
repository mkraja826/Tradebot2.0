import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from tradebot.market import MarketDataError, collect_market_snapshot

NOW = datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc)
EPOCH = int(NOW.timestamp())

PRODUCTS = [
    {"id": 1, "symbol": "BTCUSD", "state": "live",
     "contract_type": "perpetual_futures", "trading_status": "operational",
     "contract_value": "0.001"},
    {"id": 2, "symbol": "C-BTC-90000-271126", "state": "live",
     "contract_type": "call_options", "trading_status": "operational",
     "strike_price": "90000", "settlement_time": "2026-11-27T12:00:00Z"},
    {"id": 3, "symbol": "P-BTC-90000-271126", "state": "live",
     "contract_type": "put_options", "trading_status": "operational",
     "strike_price": "90000", "settlement_time": "2026-11-27T12:00:00Z"},
    {"id": 4, "symbol": "ETHUSD", "state": "live",
     "contract_type": "perpetual_futures"},
]


def ticker(pid, symbol, contract_type, *, age=5):
    return {
        "product_id": pid, "symbol": symbol, "contract_type": contract_type,
        "timestamp": EPOCH - age, "mark_price": "90002",
        "spot_price": "90000", "oi": "1000", "volume": 20,
        "quotes": {"best_bid": "90000" if pid == 1 else "100",
                   "best_ask": "90001" if pid == 1 else "102",
                   "bid_iv": "0.55", "ask_iv": "0.57"},
        "greeks": {"delta": "0.5", "gamma": "0.002", "vega": "0.1",
                   "theta": "-0.03", "rho": "0.01"},
    }


class FakeDelta:
    def __init__(self):
        self.catalog = deepcopy(PRODUCTS)
        self.quotes = [
            ticker(1, "BTCUSD", "perpetual_futures"),
            ticker(2, "C-BTC-90000-271126", "call_options"),
            ticker(3, "P-BTC-90000-271126", "put_options"),
            ticker(4, "ETHUSD", "perpetual_futures"),
        ]
        self.book = {"symbol": "BTCUSD",
                     "last_updated_at": (EPOCH - 6) * 1_000_000,
                     "buy": [{"price": "90000", "size": 5}],
                     "sell": [{"price": "90001", "size": 3}]}
        self.bars = [
            {"time": EPOCH - (23 - i) * 300,
             "open": 90000 + 5 * i,
             "high": 90005 + 5 * i, "low": 89990 + 5 * i,
             "close": 90000 + 5 * i, "volume": 1}
            for i in range(24)
        ]
        self.wallet = {"balances": [
            {"asset_symbol": "USD", "available_balance": "10000.0",
             "balance": "12000", "blocked_margin": "2000"},
            {"asset_symbol": "INR", "available_balance": "500",
             "balance": "500", "blocked_margin": "0"},
        ], "meta": {"net_equity": "12500"}}
        self.wallet_reads = 0

    def products(self):
        return deepcopy(self.catalog)

    def btc_tickers(self):
        return deepcopy(self.quotes)

    def btc_orderbook(self, *, depth=20):
        if depth != 20:
            raise AssertionError("Wrong depth")
        return deepcopy(self.book)

    def candles(self, *, symbol, resolution, start, end):
        assert symbol == "BTCUSD" and resolution == "5m"
        assert start < end and end == EPOCH
        return deepcopy(self.bars)

    def wallet_balances(self):
        self.wallet_reads += 1
        return deepcopy(self.wallet)


class MarketSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.exchange = FakeDelta()

    def collect(self, **kwargs):
        return collect_market_snapshot(self.exchange, now=NOW, **kwargs)

    def test_snapshot_includes_futures_options_greeks_and_technical(self):
        snap = self.collect()
        self.assertEqual(snap["environment"], "delta-india-demo")
        self.assertEqual(snap["core"]["best_bid"], "90000")
        self.assertEqual(snap["core"]["spread"], "1")
        self.assertEqual(len(snap["options"]), 2)
        self.assertEqual(len(snap["futures"]), 1)
        self.assertEqual(snap["options"][0]["greeks"]["delta"], "0.5")
        self.assertEqual(snap["quote_counts"]["catalog_btc_contracts"], 3)
        self.assertEqual(snap["quote_counts"]["matched_tickers"], 3)
        self.assertEqual(len(snap["technical"]["last_24"]), 24)
        self.assertGreater(snap["technical"]["return_1h_pct"], 0)
        self.assertIsNone(snap["demo_funds"])
        self.assertEqual(self.exchange.wallet_reads, 0)

    def test_demo_wallet_preserves_asset_units_and_equity(self):
        snap = self.collect(include_balances=True)
        funds = snap["demo_funds"]
        self.assertEqual(funds["net_equity"], "12500")
        self.assertEqual(funds["wallets"][0]["asset"], "USD")
        self.assertEqual(funds["wallets"][0]["available_balance"], "10000.0")
        self.assertEqual(funds["wallets"][1]["asset"], "INR")
        self.assertEqual(self.exchange.wallet_reads, 1)

    def test_stale_btc_ticker_halts_snapshot(self):
        self.exchange.quotes[0]["timestamp"] = EPOCH - 120
        with self.assertRaises(MarketDataError):
            self.collect()

    def test_stale_option_is_explicitly_marked_unusable(self):
        self.exchange.quotes[1]["timestamp"] = EPOCH - 121
        snap = self.collect()
        self.assertFalse(snap["options"][0]["usable_quote"])
        self.assertTrue(snap["options"][1]["usable_quote"])

    def test_stale_book_halts_snapshot(self):
        self.exchange.book["last_updated_at"] = (EPOCH - 90) * 1_000_000
        with self.assertRaises(MarketDataError):
            self.collect()

    def test_crossed_book_halts_snapshot(self):
        self.exchange.book["sell"][0]["price"] = "89999"
        with self.assertRaises(MarketDataError):
            self.collect()

    def test_expired_and_wrong_underlying_excluded(self):
        self.exchange.catalog[1]["state"] = "expired"
        snap = self.collect()
        self.assertEqual(len(snap["options"]), 1)
        self.assertNotIn("ETHUSD", [q["symbol"] for q in snap["futures"]])

    def test_mismatched_product_symbol_not_matched(self):
        self.exchange.quotes[1]["symbol"] = "ETHUSD"
        snap = self.collect()
        self.assertEqual(len(snap["options"]), 1)

    def test_old_candles_halt_snapshot(self):
        for row in self.exchange.bars:
            row["time"] -= 3600
        with self.assertRaises(MarketDataError):
            self.collect()

    def test_insufficient_candles_halt_snapshot(self):
        self.exchange.bars = self.exchange.bars[-5:]
        with self.assertRaises(MarketDataError):
            self.collect()

    def test_inconsistent_candle_halts_snapshot(self):
        self.exchange.bars[-1]["low"] = 100000
        with self.assertRaises(MarketDataError):
            self.collect()

    def test_negative_available_balance_halts_snapshot(self):
        self.exchange.wallet["balances"][0]["available_balance"] = "-1"
        with self.assertRaises(MarketDataError):
            self.collect(include_balances=True)

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            collect_market_snapshot(self.exchange, now=datetime(2026, 11, 18))

    def test_missing_btc_perpetual_rejected(self):
        self.exchange.catalog = self.exchange.catalog[1:]
        with self.assertRaises(MarketDataError):
            self.collect()


if __name__ == "__main__":
    unittest.main()
