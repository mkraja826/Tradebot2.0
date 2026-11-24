import unittest
from tradebot.bitcoin_strategies_v3 import RULES as B
from tradebot.gold_strategies_v3 import RULES as G,inputs
from tradebot.strategy_rules_v3 import evaluate
class BatchThreeTests(unittest.TestCase):
    def test_short_and_missing(self):
        cases={
        "B36":dict(p_rsi14=80,rsi14=65,close=9,p_close=10,upper_wick_fraction=.5,adx14=25),
        "B37":dict(rsi_bearish_divergence=1,p_macd_histogram=2,macd_histogram=1,close=9,ema9=10),
        "B38":dict(f1h_ema20=10,f1h_ema50=11,f1h_adx14=25,close=9,ema20=10,p_stoch_k14=85,stoch_k14=70,stoch_d3=75),
        "B39":dict(high=12,prior_high20=11,close=10,rvol20=3,upper_wick_fraction=.6,p_rsi14=75,rsi14=65),
        "B40":dict(p_macd_histogram=-1,macd_histogram=-2,cmf20=-.3,rvol20=2,close=9,p_close=10,ema50=11),
        "G36":dict(active_session_vwap=9,high=12,atr14=1,p_rsi14=75,rsi14=65,close=10,p_close=11),
        "G37":dict(macd_bearish_divergence=1,p_close=12,previous_day_pivot=11,close=9,ema9=10),
        "G38":dict(f4h_ema20=10,f4h_ema50=11,f4h_adx14=25,high=11,active_session_vwap=10,close=9,p_rsi14=60,rsi14=50),
        "G39":dict(high=12,previous_day_r1=11,close=10,rvol20=3,upper_wick_fraction=.6,mfi14=70),
        "G40":dict(obv_window=2,p_obv_window=3,close=9,p_close=10,ema20=10,ema50=11,cmf20=-.2,rvol20=2)}
        for r in B+G:
            if r.id not in cases: continue
            x=dict.fromkeys(r.fields.split(),0);x.update(cases[r.id])
            self.assertEqual(evaluate(r,x)["directions"],["SHORT"],r.id)
            for k in x: self.assertEqual(evaluate(r,dict(x,**{k:None}))["status"],"unavailable",r.id)
    def test_higher_frame_no_future_or_stale(self):
        item=dict(status="ready",closed_at=1800000000,features={},candle={},previous_features={},previous_candle={})
        other=dict(status="ready",closed_at=1800000000,features={"ema20":10})
        m={"frames":{"15m":item,"4h":other}}
        self.assertEqual(inputs(m,"15m")["f4h_ema20"],10)
        for offset in (1,-14400):
            other["closed_at"]=item["closed_at"]+offset
            self.assertNotIn("f4h_ema20",inputs(m,"15m"))
