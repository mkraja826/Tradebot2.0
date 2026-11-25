import unittest
from datetime import datetime,timezone
from tradebot.gold_strategies_v3 import RULES,DEFERRED,scan_gold,evaluate
from tradebot.gold_context_v3 import gold_context

class GoldRulesTests(unittest.TestCase):
    def test_registry_and_each_rule(self):
        self.assertEqual(sorted([r.id for r in RULES]+list(DEFERRED)),[f"G{i:02}" for i in range(1,51)])
        cases={
        "G46":dict(previous_week_low=8,previous_week_high=12,p_close=9,close=11,ema20=10,macd_histogram=1),
        "G47":dict(tokyo_active=1,london_active=0,close=12,open=10,rolling_vwap20=11,ema20=11,ema50=10,body_fraction=.8,rvol20=2),
        "G48":dict(indicative_gold_basis_bps=5,delta_quote_spread_bps=1,close=12,prior_high10=11,prior_low10=9,atr14=1,rvol20=2,cmf20=.2),
        "G49":dict(vix_daily=30,vix_5obs_change=5,real_yield_5obs_bp=-12,close=12,ema50=11,plus_di14=30,minus_di14=20),
        "G50":dict(f4h_ema20=11,f4h_ema50=10,f4h_macd_histogram=1,close=12,prior_high20=11,prior_low20=9,atr14=1,rvol20=2),
        "G41":dict(overlap=1,sample_flow_imbalance=.5,book_imbalance=.3,book_spread_bps=1,close=12,prior_high10=11,rvol20=2),
        "G42":dict(p_adx14=27,adx14=23,p_rsi14=30,rsi14=40,bb20_percent_b=.2,close=12,p_close=11),
        "G43":dict(p_close=9,previous_week_low=10,previous_week_high=13,close=11,lower_wick_fraction=.5,cmf20=.2),
        "G44":dict(overlap=1,atr14=1,open=10,active_session_vwap=11,close=12,ema9=11,body_fraction=.8,rvol20=2),
        "G45":dict(broad_dollar_5obs_pct=-.5,real_yield_5obs_bp=-8,low=10,ema20=11,close=12,p_rsi14=40,rsi14=50),
        "G36":dict(active_session_vwap=12,low=9,atr14=1,p_rsi14=25,rsi14=35,close=11,p_close=10),
        "G37":dict(macd_bullish_divergence=1,p_close=9,previous_day_pivot=10,close=12,ema9=11),
        "G38":dict(f4h_ema20=11,f4h_ema50=10,f4h_adx14=25,low=10,active_session_vwap=11,close=12,p_rsi14=40,rsi14=50),
        "G39":dict(low=9,previous_day_s1=10,close=11,rvol20=3,lower_wick_fraction=.6,mfi14=30),
        "G40":dict(obv_window=3,p_obv_window=2,close=12,p_close=11,ema20=11,ema50=10,cmf20=.2,rvol20=2),
        "G31":dict(london_active=1,ema20=11,ema50=10,low=10,close=12,p_rsi14=45,rsi14=55),
        "G32":dict(new_york_active=1,previous_day_s2=10,low=9,close=11,lower_wick_fraction=.6,rsi14=35),
        "G33":dict(p_close=9,p_bb20_mid=10,close=12,bb20_mid=11,ema50=10,adx14=25,roc5_pct=1),
        "G34":dict(fib_direction=1,fib_382=10,low=10,close=12,atr14=1,ema20=11,macd_histogram=1),
        "G35":dict(p_bb20_percent_b=-.1,bb20_percent_b=.2,mfi14=30,adx14=15,close=12,p_close=11),
        "G26":dict(p_stoch_k14=15,p_stoch_d3=20,stoch_k14=30,stoch_d3=25,close=12,ema20=11,ema50=10),
        "G27":dict(p_cci20=-120,cci20=-80,adx14=15,close=12,p_close=11),
        "G28":dict(p_close=9,previous_day_pivot=10,close=12,rvol20=2,macd_histogram=1),
        "G29":dict(p_supertrend_direction=-1,supertrend_direction=1,plus_di14=30,minus_di14=20,adx14=25),
        "G30":dict(p_cmf20=-.1,cmf20=.2,mfi14=65,close=12,ema20=11,roc5_pct=1),
        "G24":dict(indicative_gold_basis_bps=-25,delta_quote_spread_bps=1,close=12,p_close=10,ema9=11,rsi14=50),
        "G23":dict(vix_daily=30,vix_5obs_change=5,stress_weekly=.4,stress_weekly_change=.2,close=12,ema20=11,ema50=10,macd_histogram=1),
        "G22":dict(fomc_post_statement=1,close=12,open=10,ema9=11,rvol20=2,body_fraction=.8),
        "G18":dict(broad_dollar_5obs_pct=-.5,close=12,ema20=11,ema50=10,macd_histogram=1),
        "G19":dict(nominal_yield_5obs_bp=-10,real_yield_5obs_bp=-8,close=12,ema20=11,macd_histogram=1),
        "G01":dict(ema20=10,ema50=9,adx14=25,close=11),
        "G02":dict(ema50=10,ema200=9,macd_histogram=1),
        "G03":dict(fib_direction=1,low=10,fib_500=10,close=11,ema20=10,rsi14=55,atr14=1),
        "G04":dict(supertrend_direction=1,p_close=10,prior_high10=10,close=11,atr14=1),
        "G05":dict(london_opening=1,close=11,asian_pre_london_high=10,atr14=1,rvol20=2),
        "G06":dict(new_york_opening=1,close=11,london_pre_ny_high=10,new_york_vwap=10,rvol20=2),
        "G07":dict(overlap=1,close=11,active_session_vwap=10,adx14=25,macd_histogram=1),
        "G08":dict(tokyo_active=1,low=9,asian_prior_low=10,close=11,stoch_k14=20,adx14=15),
        "G09":dict(close=11,previous_day_high=10,atr14=1,rvol20=2),
        "G10":dict(close=11,previous_week_high=10,ema50=9),
        "G11":dict(low=9,previous_day_s1=10,close=11,lower_wick_fraction=.6),
        "G12":dict(fib_direction=1,low=10,fib_618=10,close=11,atr14=1,rsi_bullish_divergence=1),
        "G13":dict(low=10,prior_low20=10,close=11,rsi14=30,lower_wick_fraction=.5,atr14=1),
        "G14":dict(bb20_percent_b=-.1,stoch_k14=10,adx14=15),
        "G15":dict(close=8,active_session_vwap=10,atr14=1,rsi14=20),
        "G16":dict(p_atr14_percentile100=20,p_bb20_width_pct=1,bb20_width_pct=2,close=11,prior_high10=10),
        "G17":dict(p_bb20_upper=11,p_bb20_lower=9,p_keltner_upper=12,p_keltner_lower=8,close=13,keltner_upper=12,roc5_pct=1,rvol20=2)}
        for rule in RULES:
            with self.subTest(rule=rule.id):
                base=dict.fromkeys(rule.fields.split(),0)
                self.assertEqual(evaluate(rule,base)["status"],"no_signal")
                vals={**base,**cases[rule.id]}
                self.assertIn("LONG",evaluate(rule,vals)["directions"])
                for key in base:
                    self.assertEqual(evaluate(rule,{**vals,key:None})["status"],"unavailable")
    def test_single_signal_and_isolation(self):
        item={"status":"ready","closed_at":900,"features":dict(ema20=10,ema50=9,adx14=25),"candle":{"close":11},"previous_features":{},"previous_candle":{}}
        s={"as_of":900,"markets":{"XAUTUSD":{"frames":{"15m":item}},"BTCUSD":{}}}
        out=scan_gold(s)
        self.assertTrue(out["trigger_ai"])
        self.assertEqual([x["id"] for x in out["signals"]],["G01"])
        self.assertEqual(out["orders_submitted"],0)
        item["features"]["adx14"]=0
        self.assertFalse(scan_gold(s)["trigger_ai"])
    def test_london_reference_excludes_signal_bar(self):
        end=int(datetime(2026,7,1,7,5,tzinfo=timezone.utc).timestamp())
        start=end-7*3600-300
        rows=[dict(time=t,open=10,high=11,low=9,close=10,volume=1) for t in range(start,end,300)]
        rows[-1].update(high=99)
        x=gold_context(rows,[],closed_at=end,frame="5m")
        self.assertEqual(x["london_opening"],1)
        self.assertEqual(x["asian_pre_london_high"],11)
        self.assertIsNone(gold_context(rows[1:],[],closed_at=end,frame="5m")["asian_pre_london_high"])
