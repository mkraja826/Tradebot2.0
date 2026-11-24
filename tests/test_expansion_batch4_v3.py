import unittest
from tradebot.bitcoin_strategies_v3 import RULES as B
from tradebot.gold_strategies_v3 import RULES as G,inputs
from tradebot.strategy_rules_v3 import evaluate
class BatchFourTests(unittest.TestCase):
    def test_short_and_missing(self):
        cases={
        "B41":dict(sample_flow_imbalance=.5,book_imbalance=-.4,book_spread_bps=2,close=10,open=11,upper_wick_fraction=.6),
        "B42":dict(p_adx14=18,adx14=23,plus_di14=20,minus_di14=30,close=9,ema20=10,ema50=11,rvol20=2),
        "B43":dict(p_close=14,p_donchian20_prior_low=10,p_donchian20_prior_high=13,close=12,macd_histogram=-1,p_macd_histogram=1),
        "B44":dict(new_york_active=1,close=9,open=11,ema20=10,rvol20=3,body_fraction=.8,roc5_pct=-.5),
        "B45":dict(index_return_pct=-.3,mark_return_pct=-.1,basis_bps=5,frame_oi=.5,sample_flow_imbalance=-.4),
        "G41":dict(overlap=1,sample_flow_imbalance=-.5,book_imbalance=-.3,book_spread_bps=1,close=9,prior_low10=10,prior_high10=12,rvol20=2),
        "G42":dict(p_adx14=27,adx14=23,p_rsi14=70,rsi14=60,bb20_percent_b=.8,close=9,p_close=10),
        "G43":dict(p_close=14,previous_week_low=10,previous_week_high=13,close=12,upper_wick_fraction=.5,cmf20=-.2),
        "G44":dict(overlap=1,atr14=1,open=12,active_session_vwap=11,close=10,ema9=11,body_fraction=.8,rvol20=2),
        "G45":dict(broad_dollar_5obs_pct=.5,real_yield_5obs_bp=8,high=12,ema20=11,close=10,p_rsi14=60,rsi14=50)}
        for r in B+G:
            if r.id not in cases: continue
            x=dict.fromkeys(r.fields.split(),0);x.update(cases[r.id])
            self.assertEqual(evaluate(r,x)["directions"],["SHORT"],r.id)
            for k in x: self.assertEqual(evaluate(r,dict(x,**{k:None}))["status"],"unavailable",r.id)
