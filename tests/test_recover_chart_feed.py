import json
import tempfile
import unittest
from pathlib import Path
from recover_trading.chart_feed import validated, refresh, read_cache, cache_path
from recover_trading.dashboard import chart_data

class ChartFeedTests(unittest.TestCase):
    def test_partial_window_and_duplicates(self):
        def row(t,**kw):
            return dict(time=t,open=100,high=102,low=98,close=101,volume=2,**kw)
        rows,bad=validated([row(60),row(120),row(120),row(240),row(300)],"1m",300)
        self.assertEqual([x["time"] for x in rows],[60,240])
        self.assertEqual(bad,1)

    def test_independent_cache_and_selection(self):
        class Client:
            def candles(self,**kwargs):
                end=kwargs["end"]
                return [dict(time=end-60,open=100,high=150,low=50,close=101,volume=1)]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"engine";cache=Path(d)/"cache";cache.mkdir()
            refresh(cache,"BTCUSD","1m",3600,client_factory=Client)
            self.assertFalse(root.exists())
            p=chart_data(root,"BTCUSD","1m",3601,cache)
            self.assertEqual(p["source"],"demo_public_completed_candles")
            self.assertEqual(p["candles"][0]["low"],50)
            self.assertEqual(p["last_close_age_s"],1)
            self.assertEqual(chart_data(root,"XAUTUSD","1m",3601,cache)["status"],"unavailable")
            path=cache_path(cache,"BTCUSD","1m")
            path.write_text("bad")
            self.assertIsNone(read_cache(cache,"BTCUSD","1m",3601))

if __name__=="__main__":
    unittest.main()
