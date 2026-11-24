import unittest
from tradebot.delta import DEMO_API
from tradebot.market_data_v3 import collect, normalize, FRAMES

NOW=1800000040

def candles(frame,count=5):
    step=FRAMES[frame]; end=NOW//step*step
    return [dict(time=t,open=10,high=12,low=9,close=11,volume=4)
            for t in range(end-count*step,end,step)]

class Feed:
    base_url=DEMO_API
    allow_orders=False
    def __init__(self): self.calls=[]
    def candles(self,*,symbol,resolution,start,end):
        self.calls.append((symbol,resolution,start,end))
        if symbol=="XAUTUSD" and resolution=="3m": raise RuntimeError("offline")
        return candles(resolution)

class MarketDataTests(unittest.TestCase):
    def test_all_frames_sort_and_ignore_open_bar(self):
        for frame in FRAMES:
            rows=candles(frame)
            rows.append(dict(rows[-1],time=rows[-1]["time"]+FRAMES[frame]))
            self.assertEqual(normalize(rows[::-1],frame,as_of=NOW,count=5),candles(frame))
    def test_missing_duplicate_and_invalid(self):
        for rows in (candles("5m")[1:],candles("5m")+candles("5m")[:1],
                     [dict(candles("5m")[0],low=99)]+candles("5m")[1:],
                     [dict(candles("5m")[0],volume=float("nan"))]+candles("5m")[1:],
                     [dict(candles("5m")[0],open=True)]+candles("5m")[1:]):
            with self.assertRaises(ValueError):
                normalize(rows,"5m",as_of=NOW,count=5)
    def test_stale_window(self):
        with self.assertRaisesRegex(ValueError,"missing_or_stale"):
            normalize(candles("5m"),"5m",as_of=NOW+300,count=5)
    def test_independent_assets_and_frames(self):
        feed=Feed()
        btc=collect(feed,"BTCUSD",as_of=NOW,count=5)
        gold=collect(feed,"XAUTUSD",as_of=NOW,count=5)
        self.assertEqual(len(feed.calls),16)
        self.assertTrue(all(v["status"]=="ready" for v in btc["frames"].values()))
        self.assertEqual(gold["frames"]["3m"]["status"],"unavailable")
        self.assertEqual(gold["frames"]["5m"]["status"],"ready")
        self.assertEqual(gold["frames"]["3m"]["bars"],[])
    def test_non_demo_or_order_enabled_rejected(self):
        for attr,val in (("base_url","https://invalid"),("allow_orders",True)):
            feed=Feed(); setattr(feed,attr,val)
            with self.assertRaises(ValueError): collect(feed,"BTCUSD",as_of=NOW,count=5)
            self.assertEqual(feed.calls,[])
    def test_invalid_frames(self):
        for frames in ([],["1m","1m"],["7m"]):
            with self.assertRaises(ValueError): collect(Feed(),"BTCUSD",frames=frames,count=5)
