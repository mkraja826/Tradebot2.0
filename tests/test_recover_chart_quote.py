import tempfile
import unittest
from recover_trading.chart_quote import normalize,refresh_quote,read_quote

class ChartQuoteTests(unittest.TestCase):
    def test_age_and_identity(self):
        class Client:
            def ticker(self,symbol):
                return dict(symbol=symbol,close="100.5",mark_price="101",timestamp=999_000_000)
        with tempfile.TemporaryDirectory() as d:
            refresh_quote(d,"BTCUSD",Client,lambda:1000)
            self.assertEqual(read_quote(d,"BTCUSD",1001)["status"],"observed")
            self.assertEqual(read_quote(d,"BTCUSD",1016)["status"],"stale")
            self.assertEqual(read_quote(d,"XAUTUSD",1001)["status"],"unavailable")
            self.assertEqual(read_quote(d,"BTCUSD",1001)["last_price"],100.5)
    def test_invalid_fields(self):
        with self.assertRaises(ValueError):
            normalize("BTCUSD",{"symbol":"XAUTUSD"},1000)
        with self.assertRaises(ValueError):
            normalize("BTCUSD",{"symbol":"BTCUSD","timestamp":999_000_000,"close":True,"mark_price":1},1000)
