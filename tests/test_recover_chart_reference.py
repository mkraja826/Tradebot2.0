import tempfile
import unittest
from recover_trading.chart_feed import refresh,read_cache,REFERENCE_SOURCE
from recover_trading.dashboard import reference_chart
from recover_trading.chart_quote import normalize,REFERENCE_SOURCE as QUOTE_SOURCE

class ReferenceChartTests(unittest.TestCase):
    def test_no_mixing(self):
        class Client:
            def candles(self,**kwargs):
                return [dict(time=kwargs["end"]-60,open=100,high=102,low=99,close=101,volume=2)]
        with tempfile.TemporaryDirectory() as d:
            refresh(d,"XAUTUSD","1m",3600,Client,source=REFERENCE_SOURCE)
            self.assertIsNone(read_cache(d,"XAUTUSD","1m",3601))
            p=reference_chart("XAUTUSD","1m",3601,d)
            self.assertEqual(p["source"],REFERENCE_SOURCE)
            self.assertEqual(p["candles"][0]["close"],101)
            self.assertEqual(reference_chart("BTCUSD","1m",3601,d)["status"],"unavailable")
    def test_quote_identity(self):
        p=normalize("XAUTUSD",dict(symbol="XAUTUSD",close="101",mark_price="100",timestamp=999000000),1000,source=QUOTE_SOURCE)
        self.assertEqual(p["source"],QUOTE_SOURCE)
