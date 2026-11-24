import unittest
from tradebot.bitcoin_strategies_v3 import RULES as B,DEFERRED as BD
from tradebot.gold_strategies_v3 import RULES as G,DEFERRED as GD
from tradebot.strategy_rules_v3 import evaluate
class BatchFiveTests(unittest.TestCase):
    def test_short_and_missing(self):
        cases={
        "B46":dict(p_ema20=11,p_ema50=10,ema20=9,ema50=10,close=8,ema200=11,roc20_pct=-1),
        "B47":dict(frame_oi=1,sample_flow_imbalance=-.5,book_spread_bps=1,ema9=10,ema21=11,high=11,close=9,p_close=10),
        "B48":dict(atr14=1,close=12,p_close=13,rolling_vwap20=10,p_cci20=170,cci20=130,adx14=15),
        "B49":dict(atr14=1,previous_day_high=12,previous_day_low=10,p_close=9,high=10,close=8,cmf20=-.2),
        "B50":dict(p_return_std20_pct=.5,return_std20_pct=.8,roc5_pct=-.6,close=9,prior_low10=10,prior_high10=12,rvol20=2),
        "G46":dict(previous_week_low=8,previous_week_high=12,p_close=11,close=9,ema20=10,macd_histogram=-1),
        "G47":dict(tokyo_active=1,london_active=0,close=9,open=11,rolling_vwap20=10,ema20=10,ema50=11,body_fraction=.8,rvol20=2),
        "G48":dict(indicative_gold_basis_bps=-5,delta_quote_spread_bps=1,close=9,prior_low10=10,prior_high10=12,atr14=1,rvol20=2,cmf20=-.2),
        "G49":dict(vix_daily=15,vix_5obs_change=-5,real_yield_5obs_bp=12,close=9,ema50=10,plus_di14=20,minus_di14=30),
        "G50":dict(f4h_ema20=10,f4h_ema50=11,f4h_macd_histogram=-1,close=9,prior_low20=10,prior_high20=12,atr14=1,rvol20=2)}
        for r in B+G:
            if r.id not in cases: continue
            x=dict.fromkeys(r.fields.split(),0);x.update(cases[r.id])
            self.assertEqual(evaluate(r,x)["directions"],["SHORT"],r.id)
            for k in x: self.assertEqual(evaluate(r,dict(x,**{k:None}))["status"],"unavailable",r.id)
    def test_registry(self):
        self.assertEqual((len(B),len(G)),(48,47))
        self.assertEqual(set(BD)|set(GD),{"B17","B18","G20","G21","G25"})
