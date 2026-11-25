import unittest
from recover_trading.dynamic_bracket import evidence,distances,MODELS

class DynamicBracketTests(unittest.TestCase):
    def test_no_future_candle(self):
        at=1800000000
        bars={t:{"time":t,"open":100,"high":101,"low":99,"close":100,"volume":1} for t in range(at-250*900,at,900)}
        x=evidence(bars,at)
        self.assertEqual(x["closed_at"],at)
        self.assertAlmostEqual(x["atr"],2)
        bars[at]={"time":at,"open":100,"high":999,"low":1,"close":500,"volume":1}
        self.assertEqual(evidence(bars,at),x)
        del bars[at-900]
        self.assertIsNone(evidence(bars,at))
    def test_atr_and_structure(self):
        e={"atr":1,"close":100,"prior_high":104,"prior_low":98}
        self.assertEqual(distances(e,"LONG","atr_1x_2x"),(100,200))
        self.assertEqual(distances(e,"LONG","structure_atr"),(200,400))
        self.assertEqual(distances(e,"SHORT","structure_atr"),(400,200))
        self.assertEqual(distances(e,"LONG","structure_buffered"),(250,450))
        for m in MODELS:
            self.assertTrue(all(v>0 for v in distances(e,"SHORT",m)))
