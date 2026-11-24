import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.market_store_v3 import MarketStore
from tradebot.market_intelligence_v3 import ticker_features,book_features
from test_market_data_v3 import candles,NOW

class IntelligenceTests(unittest.TestCase):
    def ticker(self):
        return dict(symbol="BTCUSD",timestamp=NOW*1000000,mark_price="101",
                    spot_price="100",oi="4",funding_rate="-0.01",
                    quotes={"best_bid":"100","best_ask":"102"})
    def book(self):
        return dict(symbol="BTCUSD",last_updated_at=NOW*1000000,
                    buy=[{"price":100,"size":3},{"price":99,"size":1}],
                    sell=[{"price":102,"size":2},{"price":103,"size":2}])
    def test_ticker(self):
        t=ticker_features(self.ticker(),"BTCUSD",NOW)
        self.assertAlmostEqual(t["mark_spot_basis_bps"],100)
        self.assertEqual(t["funding_rate_raw"],-.01)
        self.assertEqual(t["open_interest_raw"],4)
    def test_book(self):
        b=book_features(self.book(),"BTCUSD",NOW)
        self.assertEqual(b["imbalance"],0)
        self.assertEqual(b["levels_each"],2)
    def test_stale_wrong_asset_crossed(self):
        for row in (dict(self.ticker(),timestamp=(NOW-61)*1000000),
                    dict(self.ticker(),symbol="XAUTUSD"),
                    dict(self.ticker(),quotes={"best_bid":102,"best_ask":101})):
            with self.assertRaises(ValueError): ticker_features(row,"BTCUSD",NOW)
    def test_bad_levels(self):
        for row in (dict(self.book(),buy=self.book()["buy"][::-1]),
                    dict(self.book(),buy=[{"price":103,"size":3}]),
                    dict(self.book(),sell=[{"price":102,"size":-1}])):
            with self.assertRaises(ValueError): book_features(row,"BTCUSD",NOW)
    def test_store_isolation_and_idempotency(self):
        with TemporaryDirectory() as d:
            path=Path(d)/"data.sqlite"
            s=MarketStore(path)
            bars=candles("5m")
            self.assertEqual(s.candles("BTCUSD","5m",bars,as_of=NOW),5)
            self.assertEqual(s.candles("BTCUSD","5m",bars,as_of=NOW),0)
            self.assertEqual(s.candles("XAUTUSD","5m",bars,as_of=NOW),5)
            t=ticker_features(self.ticker(),"BTCUSD",NOW)
            self.assertEqual(s.intelligence("BTCUSD","ticker",t),1)
            self.assertEqual(s.intelligence("BTCUSD","ticker",t),0)
            s=MarketStore(path)
            self.assertEqual(s.history("BTCUSD","candle:5m"),bars)
            self.assertEqual(s.history("BTCUSD","ticker"),[t])
            self.assertEqual(s.history("XAUTUSD","ticker"),[])
            self.assertEqual(s.history("BTCUSD","candle:5m",2),bars[-2:])
            with self.assertRaisesRegex(ValueError,"conflicting_observation"):
                s.intelligence("BTCUSD","ticker",dict(t,open_interest_raw=7))
            self.assertEqual(s.history("BTCUSD","ticker"),[t])
