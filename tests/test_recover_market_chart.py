import json,sqlite3,tempfile,unittest
from pathlib import Path
from recover_trading.dashboard import chart_data,CHART_FRAMES
class MarketChartTests(unittest.TestCase):
    def test_market_frame_and_completed_candles(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"BTCUSD";p.mkdir()
            with sqlite3.connect(p/"market.sqlite") as db:
                db.execute("CREATE TABLE samples(symbol TEXT,series TEXT,stamp INTEGER,payload TEXT)")
                def row(t,**kw):
                    r={"time":t,"open":10,"high":12,"low":9,"close":11,"volume":5,**kw}
                    db.execute("INSERT INTO samples VALUES(?,?,?,?)",("BTCUSD","candle:5m",t,json.dumps(r)))
                row(300);row(600,low=20);row(900);row(1200)
            r=chart_data(tmp,"BTCUSD","5m",1250)
            self.assertEqual([c["time"] for c in r["candles"]],[300,900])
            self.assertEqual(r["invalid_rows"],1);self.assertEqual(r["gap_count"],1)
            self.assertEqual(chart_data(tmp,"XAUTUSD","5m",1250)["status"],"unavailable")
    def test_invalid_market_or_timeframe(self):
        self.assertEqual(len(CHART_FRAMES),8)
        for s,f in (("../","5m"),("BTCUSD","2m")):
            with self.assertRaises(ValueError):chart_data(".",s,f,1000)
