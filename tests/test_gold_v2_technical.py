import unittest
from recover_trading.gold_v2_engine import Bar,evaluate,quality,FRAMES
from recover_trading.gold_v2_technical import momentum,directional_strength,rolling_vwap,swings,features,candidates

NOW=3600000
def series(step=300,slope=0.1,volume=1):
    return [Bar(NOW-(219-i)*step,3000+i*slope,3001+i*slope,
                2999+i*slope,3000+i*slope,volume) for i in range(220)]

class TechnicalTests(unittest.TestCase):
    def test_rsi_up_down_flat(self):
        self.assertEqual(momentum(series()),100)
        self.assertEqual(momentum(series(slope=-0.1)),0)
        self.assertEqual(momentum(series(slope=0)),50)
    def test_adx_uptrend(self):
        x=directional_strength(series())
        self.assertAlmostEqual(x["adx"],100)
        self.assertGreater(x["plus_di"],x["minus_di"])
    def test_adx_downtrend(self):
        x=directional_strength(series(slope=-0.1))
        self.assertAlmostEqual(x["adx"],100)
        self.assertGreater(x["minus_di"],x["plus_di"])
    def test_vwap_zero_volume(self):
        self.assertIsNone(rolling_vwap(series(volume=0)))
    def test_vwap(self):
        b=series()
        self.assertAlmostEqual(rolling_vwap(b),sum(x.c for x in b[-20:])/20)
    def test_unconfirmed_pivot(self):
        b=series()
        self.assertIsNone(swings(b)["last_swing_high"])
        b[-1]=Bar(NOW,3000,4000,2999,3000,1)
        self.assertIsNone(swings(b)["last_swing_high"])
    def test_volume_breakout_long(self):
        b=series();last=b[-1]
        b[-1]=Bar(last.ts,last.o,last.o+3,last.o-1,last.o+2.5,2)
        self.assertIn(("volume_confirmed_breakout",1),candidates(b,features(b),1,1,2))
    def test_volume_breakout_short(self):
        b=series(slope=-0.1);last=b[-1]
        b[-1]=Bar(last.ts,last.o,last.o+1,last.o-3,last.o-2.5,2)
        self.assertIn(("volume_confirmed_breakout",-1),candidates(b,features(b),-1,-1,2))
    def test_no_volume_confirmation(self):
        b=series();last=b[-1]
        b[-1]=Bar(last.ts,last.o,last.o+3,last.o-1,last.o+2.5,0)
        self.assertNotIn(("volume_confirmed_breakout",1),candidates(b,features(b),1,1,2))
    def test_historical_wick(self):
        b=series();x=b[100]
        b[100]=Bar(x.ts,x.o,x.h+100,x.l,x.c,x.volume)
        self.assertEqual(quality(b,300,NOW),"historical_extreme_range_unverified")
    def test_integrated_features(self):
        result=evaluate({s:series(s) for s in FRAMES},NOW)
        self.assertEqual(result["status"],"observed")
        self.assertEqual(result["version"],"gold-v2-alpha.3")
        self.assertIn("adx",result["features"][300])
