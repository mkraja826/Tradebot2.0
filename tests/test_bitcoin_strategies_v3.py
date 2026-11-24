import unittest
from tradebot.bitcoin_strategies_v3 import RULES,DEFERRED,evaluate,scan_btc
class BitcoinRulesTests(unittest.TestCase):
    def test_registry(self):
        ids=[r.id for r in RULES]+list(DEFERRED)
        self.assertEqual(sorted(ids),[f"B{i:02}" for i in range(1,51)])
        self.assertEqual(len(RULES),48)
    def test_all_rules_positive_and_missing(self):
        cases={
        "B46":dict(p_ema20=10,p_ema50=11,ema20=12,ema50=11,close=13,ema200=10,roc20_pct=1),
        "B47":dict(frame_oi=1,sample_flow_imbalance=.5,book_spread_bps=1,ema9=11,ema21=10,low=10,close=12,p_close=11),
        "B48":dict(atr14=1,close=10,p_close=9,rolling_vwap20=12,p_cci20=-170,cci20=-130,adx14=15),
        "B49":dict(atr14=1,previous_day_high=10,previous_day_low=8,p_close=11,low=10,close=12,cmf20=.2),
        "B50":dict(p_return_std20_pct=.5,return_std20_pct=.8,roc5_pct=.6,close=12,prior_high10=11,prior_low10=9,rvol20=2),
        "B41":dict(sample_flow_imbalance=-.5,book_imbalance=.4,book_spread_bps=2,close=12,open=11,lower_wick_fraction=.6),
        "B42":dict(p_adx14=18,adx14=23,plus_di14=30,minus_di14=20,close=12,ema20=11,ema50=10,rvol20=2),
        "B43":dict(p_close=9,p_donchian20_prior_low=10,p_donchian20_prior_high=13,close=11,macd_histogram=1,p_macd_histogram=-1),
        "B44":dict(new_york_active=1,close=12,open=10,ema20=11,rvol20=3,body_fraction=.8,roc5_pct=.5),
        "B45":dict(index_return_pct=.3,mark_return_pct=.1,basis_bps=-5,frame_oi=.5,sample_flow_imbalance=.4),
        "B36":dict(p_rsi14=20,rsi14=30,close=12,p_close=11,lower_wick_fraction=.5,adx14=25),
        "B37":dict(rsi_bullish_divergence=1,p_macd_histogram=-2,macd_histogram=-1,close=12,ema9=11),
        "B38":dict(f1h_ema20=11,f1h_ema50=10,f1h_adx14=25,close=12,ema20=11,p_stoch_k14=15,stoch_k14=30,stoch_d3=25),
        "B39":dict(low=9,prior_low20=10,close=11,rvol20=3,lower_wick_fraction=.6,p_rsi14=25,rsi14=35),
        "B40":dict(p_macd_histogram=1,macd_histogram=2,cmf20=.3,rvol20=2,close=12,p_close=11,ema50=10),
        "B31":dict(ema20=11,ema50=10,p_close=9,p_keltner20_mid=10,low=10,keltner20_mid=11,close=12,macd_histogram=1),
        "B32":dict(p_cci20=80,cci20=120,rvol20=2,close=12,prior_high10=11),
        "B33":dict(p_atr14_percentile100=20,atr14_percentile100=80,close=12,prior_high50=11,prior_low50=8,body_fraction=.8),
        "B34":dict(low=9,p_confirmed_swing_low=10,close=11,rsi14=50,cmf20=.2),
        "B35":dict(frame_oi=-1,p_close=10,open=10,close=11,lower_wick_fraction=.6,rvol20=2),
        "B26":dict(plus_di14=30,minus_di14=20,p_plus_di14=15,p_minus_di14=25,adx14=25,close=12,ema20=11),
        "B27":dict(p_mfi14=15,mfi14=25,rsi14=40,close=12,p_close=11,adx14=15),
        "B28":dict(p_tenkan9=9,p_kijun26=10,tenkan9=12,kijun26=11,close=13,ichimoku_span_b_unshifted=12),
        "B29":dict(close=12,donchian55_prior_high=10,atr14=1,ema50=11,rvol20=2),
        "B30":dict(p_close=9,p_rolling_vwap20=10,close=12,rolling_vwap20=10,ema20=11,cmf20=.2),
        "B01":dict(ema9=10,ema21=9,adx14=30,ema9_slope=1,close=11),
        "B02":dict(ema50=10,ema200=9,macd_histogram=1),
        "B03":dict(rsi14=60,macd_histogram=1,p_macd_histogram=-1,rvol20=2),
        "B04":dict(ema20=10,ema50=9,low=10,close=11,stoch_k14=21,p_stoch_k14=19,atr14=1),
        "B05":dict(supertrend_direction=1,adx14=30,atr14_pct=1,close=11,supertrend10_3=10),
        "B06":dict(p_bb20_upper=11,p_bb20_lower=9,p_keltner_upper=12,p_keltner_lower=8,close=13,bb20_upper=12,rvol20=2),
        "B07":dict(close=12,donchian20_prior_high=10,atr14=1),
        "B08":dict(p_close=11,p_prior_high20=10,low=10,close=11,ema20=9,rvol20=1,atr14=1),
        "B09":dict(atr14_percentile100=90,rvol20=2,close=11,open=10,body_fraction=.8),
        "B10":dict(p_inside=1,p_high=10,p_low=8,close=11,rvol20=2),
        "B11":dict(low=8,prior_low20=9,close=10,lower_wick_fraction=.6,rvol20=2),
        "B12":dict(low=8,prior_low20=9,close=10,rsi_bullish_divergence=1),
        "B13":dict(rsi14=30,macd_bullish_divergence=1),
        "B14":dict(rsi14=20,bb20_percent_b=-.1,adx14=15),
        "B15":dict(p_close=9,p_utc_day_vwap=10,close=12,utc_day_vwap=11,ema9=10,rvol20=2),
        "B16":dict(close=7,utc_day_vwap=10,atr14=1,rsi14=20),
        "B19":dict(frame_oi=1,rvol20=2,close=11,p_close=10,roc5_pct=1),
        "B20":dict(funding_prior_z=-3,funding_latest_z=-1,close=11,ema9=10),
        "B22":dict(basis_prior_bps=-10,basis_bps=-5,index_return_pct=.1,mark_return_pct=.2,sample_flow_imbalance=.5),
        "B21":dict(sample_flow_imbalance=.5,book_imbalance=.3,book_spread_bps=1,close=11,ema9=10),
        "B23":dict(obv_window=2,p_obv_window=1,cmf20=.2,bb20_width_pct=1,p_bb20_width_pct=2,close=11,p_close=10),
        "B24":dict(weekend=1,close=12,prior_high20=10,atr14=1,rvol20=2),
        "B25":dict(ema9=10,ema21=9,macd_histogram=1,f15_ema20=10,f15_ema50=9,f1h_ema20=10,f1h_ema50=9)}
        for rule in RULES:
            with self.subTest(rule=rule.id):
                base=dict.fromkeys(rule.fields.split(),0)
                self.assertEqual(evaluate(rule,base)["status"],"no_signal")
                vals={**base,**cases[rule.id]}
                self.assertIn("LONG",evaluate(rule,vals)["directions"])
                for key in base:
                    self.assertEqual(evaluate(rule,{**vals,key:None})["status"],"unavailable")
    def test_one_signal_and_independent_market(self):
        item={"status":"ready","closed_at":300,"features":dict(ema9=10,ema21=9,adx14=30,ema9_slope=1),"candle":{"close":11},"previous_features":{},"previous_candle":{}}
        s={"as_of":300,"markets":{"BTCUSD":{"frames":{"5m":item}},"XAUTUSD":{}}}
        r=scan_btc(s)
        self.assertTrue(r["trigger_ai"])
        self.assertEqual([x["id"] for x in r["signals"]],["B01"])
        self.assertFalse(r["ai_dispatched"]); self.assertEqual(r["orders_submitted"],0)
        item["features"]["adx14"]=0
        self.assertFalse(scan_btc(s)["trigger_ai"])
