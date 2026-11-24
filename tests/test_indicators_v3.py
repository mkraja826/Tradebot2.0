import unittest
from math import isfinite
from statistics import mean,pstdev
from tradebot.indicators_v3 import features
from tradebot.market_data_v3 import FRAMES
NOW=1800050000

def bars(frame="5m",n=250,mode="up"):
    step=FRAMES[frame]; end=NOW//step*step
    values=[100+i if mode=="up" else 400-i if mode=="down" else 100 for i in range(n)]
    return [dict(time=end-(n-i)*step,open=c,high=c+1,low=c-1,close=c,volume=10) for i,c in enumerate(values)]

class IndicatorsTests(unittest.TestCase):
    def get(self,mode="up",n=250,frame="5m"):
        return features(bars(frame,n,mode),"BTCUSD",frame,as_of=NOW)["features"]
    def test_rising_closed_form(self):
        x=self.get()
        self.assertAlmostEqual(x["ema20"],349-9.5)
        self.assertAlmostEqual(x["ema200"],349-99.5)
        self.assertEqual(x["sma20"],339.5)
        self.assertEqual(x["rsi14"],100)
        self.assertEqual(x["adx14"],100)
        self.assertEqual(x["atr14"],2)
        self.assertAlmostEqual(x["macd_line"],7)
        self.assertAlmostEqual(x["macd_histogram"],0)
        self.assertEqual(x["obv_window"],2490)
        self.assertEqual(x["rvol20"],1)
        self.assertEqual(x["mfi14"],100)
        self.assertEqual(x["cmf20"],0)
        self.assertAlmostEqual(x["bb20_upper"],339.5+2*pstdev(range(330,350)))
        self.assertEqual(x["donchian20_prior_high"],349)
        self.assertEqual(x["prior_low20"],328)
    def test_falling_flat(self):
        x=self.get("down"); self.assertEqual(x["rsi14"],0); self.assertEqual(x["mfi14"],0)
        self.assertLess(x["obv_window"],0)
        x=self.get("flat"); self.assertEqual(x["rsi14"],50); self.assertEqual(x["adx14"],0)
        self.assertIsNone(x["bb20_percent_b"]); self.assertIsNone(x["mfi14"])
    def test_short_daily_history(self):
        x=self.get(n=180,frame="1d")
        self.assertIsNone(x["ema200"]); self.assertIsNone(x["sma200"]); self.assertIsNotNone(x["ema50"])
    def test_invalid_and_missing(self):
        for rows in (bars()[1:-1],bars()[:-2]+bars()[-1:],bars()[:-1]+[dict(bars()[-1],volume=-1)]):
            with self.assertRaises(ValueError): features(rows,"BTCUSD","5m",as_of=NOW)
    def test_all_frames_and_assets(self):
        for frame in FRAMES:
            for symbol in ("BTCUSD","XAUTUSD"):
                result=features(bars(frame),symbol,frame,as_of=NOW)
                self.assertGreaterEqual(len(result["features"]),40)
                self.assertTrue(all(x is None or isfinite(x) for x in result["features"].values()))
    def test_no_volume_or_incomplete_day(self):
        rows=[dict(x,volume=0) for x in bars("1m",20)]
        x=features(rows,"XAUTUSD","1m",as_of=NOW)["features"]
        for k in ("rolling_vwap20","rvol20","cmf20","mfi14","utc_day_vwap"): self.assertIsNone(x[k])
