import unittest
from tradebot.bitcoin_strategies_v3 import RULES as B
from tradebot.gold_strategies_v3 import RULES as G
from tradebot.strategy_rules_v3 import evaluate
from tradebot.strategy_registry_v3 import valid_signal_rule
class BatchTwoTests(unittest.TestCase):
    def test_short_and_missing(self):
        cases={
        "B31":dict(ema20=10,ema50=11,p_close=12,p_keltner20_mid=11,high=11,keltner20_mid=10,close=9,macd_histogram=-1),
        "B32":dict(p_cci20=-80,cci20=-120,rvol20=2,close=9,prior_low10=10),
        "B33":dict(p_atr14_percentile100=20,atr14_percentile100=80,close=9,prior_low50=10,prior_high50=12,body_fraction=.8),
        "B34":dict(high=12,p_confirmed_swing_high=11,close=10,rsi14=50,cmf20=-.2),
        "B35":dict(frame_oi=-1,p_close=11,open=11,close=10,upper_wick_fraction=.6,rvol20=2),
        "G31":dict(london_active=1,ema20=10,ema50=11,high=11,close=9,p_rsi14=55,rsi14=45),
        "G32":dict(new_york_active=1,previous_day_r2=11,high=12,close=10,upper_wick_fraction=.6,rsi14=65),
        "G33":dict(p_close=12,p_bb20_mid=11,close=9,bb20_mid=10,ema50=11,adx14=25,roc5_pct=-1),
        "G34":dict(fib_direction=-1,fib_382=11,high=11,close=9,atr14=1,ema20=10,macd_histogram=-1),
        "G35":dict(p_bb20_percent_b=1.1,bb20_percent_b=.8,mfi14=70,adx14=15,close=9,p_close=10)}
        for r in B+G:
            if r.id not in cases: continue
            x=dict.fromkeys(r.fields.split(),0);x.update(cases[r.id])
            self.assertEqual(evaluate(r,x)["directions"],["SHORT"],r.id)
            for k in x:
                self.assertEqual(evaluate(r,dict(x,**{k:None}))["status"],"unavailable",r.id)
            self.assertTrue(valid_signal_rule("BTCUSD" if r.id[0]=="B" else "XAUTUSD",r.id,r.frames[0]))
