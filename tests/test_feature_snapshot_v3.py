import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from tradebot.market_store_v3 import MarketStore
from tradebot.feature_snapshot_v3 import snapshot
from test_indicators_v3 import bars,NOW

class SnapshotTests(unittest.TestCase):
    def test_independent_assets_and_no_future_candle(self):
        with TemporaryDirectory() as d:
            path=Path(d)/"research.sqlite"; s=MarketStore(path)
            btc=bars("5m"); s.candles("BTCUSD","5m",btc,as_of=NOW)
            future=dict(btc[-1],time=btc[-1]["time"]+300)
            s.candles("BTCUSD","5m",[future],as_of=NOW+300)
            s.candles("XAUTUSD","1d",bars("1d",180),as_of=NOW)
            result=snapshot(path,NOW)["markets"]
            a=result["BTCUSD"]["frames"]["5m"]
            self.assertEqual(a["status"],"ready")
            self.assertEqual(a["closed_at"],NOW//300*300)
            self.assertEqual(a["features"]["sma20"],339.5)
            self.assertEqual(len(a["features"]),76)
            self.assertEqual(result["BTCUSD"]["frames"]["1d"]["status"],"unavailable")
            self.assertEqual(result["XAUTUSD"]["frames"]["5m"]["status"],"unavailable")
            self.assertEqual(result["XAUTUSD"]["frames"]["1d"]["status"],"ready")
            self.assertEqual(result["XAUTUSD"]["context"]["previous_day_close"],279)
