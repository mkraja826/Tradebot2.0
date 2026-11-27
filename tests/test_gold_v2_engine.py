"""Synthetic tests; no exchange, network, or credentials."""
import unittest
from recover_trading.gold_v2_engine import Bar, evaluate, quality, ema, atr, FRAMES

NOW = 3600*1000

def series(seconds, slope=0.1):
    end = NOW - NOW%seconds
    return [Bar(end-(219-i)*seconds, 3000+i*slope, 3001+i*slope,
                2999+i*slope, 3000+i*slope, 1.0) for i in range(220)]

class GoldV2Tests(unittest.TestCase):
    def setUp(self):
        self.frames = {s:series(s) for s in FRAMES}

    def test_ema_constant(self):
        self.assertAlmostEqual(ema([5.0]*210,200),5.0)

    def test_atr(self):
        self.assertAlmostEqual(atr(self.frames[300]),2.0)

    def test_clean_data(self):
        x=evaluate(self.frames,NOW)
        self.assertEqual(x["status"],"observed")
        self.assertEqual(x["execution_effect"],"none")
        self.assertEqual(x["features"][3600]["direction"],1)

    def test_missing_data(self):
        self.frames.pop(900)
        self.assertEqual(evaluate(self.frames,NOW)["status"],"data_unusable")

    def test_future_bar(self):
        self.assertEqual(quality(self.frames[300],300,NOW-1),
                         "future_misaligned_or_gap")

    def test_gap(self):
        del self.frames[300][100]
        self.assertEqual(quality(self.frames[300],300,NOW),
                         "future_misaligned_or_gap")

    def test_extreme_wick(self):
        b=self.frames[300][-1]
        self.frames[300][-1]=Bar(b.ts,b.o,b.h+100,b.l,b.c,b.volume)
        self.assertEqual(quality(self.frames[300],300,NOW),
                         "extreme_range_unverified")

    def test_sweep(self):
        b=self.frames[300]
        low=min(x.l for x in b[-22:-2])
        b[-1]=Bar(b[-1].ts,low-0.2,low+1.2,low-0.5,low+0.5,1)
        x=evaluate(self.frames,NOW)
        self.assertIn(("liquidity_sweep","LONG"),
                      [(c["family"],c["direction"]) for c in x["candidates"]])

if __name__=="__main__":
    unittest.main()
