"""BTC-specific candidate hypotheses. Thresholds are uncalibrated research settings."""
from dataclasses import dataclass
from math import isfinite

from tradebot.strategy_rules_v3 import Rule,evaluate
from tradebot.trade_flow_v3 import inputs as flow_inputs

def rule(i,name,frames,fields,long,short):
    return Rule(f"B{i:02}",name,tuple(frames.split()),fields,long,short)

RULES=[
rule(1,"trend_continuation","5m 15m","ema9 ema21 adx14 ema9_slope close",
 lambda x:x["ema9"]>x["ema21"] and x["adx14"]>=25 and x["ema9_slope"]>0 and x["close"]>x["ema9"],
 lambda x:x["ema9"]<x["ema21"] and x["adx14"]>=25 and x["ema9_slope"]<0 and x["close"]<x["ema9"]),
rule(2,"major_trend","1h 4h","ema50 ema200 macd_histogram",
 lambda x:x["ema50"]>x["ema200"] and x["macd_histogram"]>0,
 lambda x:x["ema50"]<x["ema200"] and x["macd_histogram"]<0),
rule(3,"momentum_ignition","5m","rsi14 macd_histogram p_macd_histogram rvol20",
 lambda x:x["rsi14"]>55 and x["macd_histogram"]>0>=x["p_macd_histogram"] and x["rvol20"]>=1.5,
 lambda x:x["rsi14"]<45 and x["macd_histogram"]<0<=x["p_macd_histogram"] and x["rvol20"]>=1.5),
rule(4,"trend_pullback","5m 15m","ema20 ema50 close low high stoch_k14 p_stoch_k14 atr14",
 lambda x:x["ema20"]>x["ema50"] and abs(x["low"]-x["ema20"])<=x["atr14"] and x["close"]>x["ema20"] and x["stoch_k14"]>20>=x["p_stoch_k14"],
 lambda x:x["ema20"]<x["ema50"] and abs(x["high"]-x["ema20"])<=x["atr14"] and x["close"]<x["ema20"] and x["stoch_k14"]<80<=x["p_stoch_k14"]),
rule(5,"strong_trend","15m","supertrend_direction adx14 atr14_pct close supertrend10_3",
 lambda x:x["supertrend_direction"]==1 and x["adx14"]>=25 and x["atr14_pct"]>0 and x["close"]>x["supertrend10_3"],
 lambda x:x["supertrend_direction"]==-1 and x["adx14"]>=25 and x["atr14_pct"]>0 and x["close"]<x["supertrend10_3"]),
rule(6,"volatility_squeeze","5m 15m","p_bb20_upper p_bb20_lower p_keltner_upper p_keltner_lower close bb20_upper bb20_lower rvol20",
 lambda x:x["p_bb20_upper"]<x["p_keltner_upper"] and x["p_bb20_lower"]>x["p_keltner_lower"] and x["close"]>x["bb20_upper"] and x["rvol20"]>=1.3,
 lambda x:x["p_bb20_upper"]<x["p_keltner_upper"] and x["p_bb20_lower"]>x["p_keltner_lower"] and x["close"]<x["bb20_lower"] and x["rvol20"]>=1.3),
rule(7,"channel_breakout","15m 1h","close donchian20_prior_high donchian20_prior_low atr14",
 lambda x:x["close"]>x["donchian20_prior_high"]+.1*x["atr14"],
 lambda x:x["close"]<x["donchian20_prior_low"]-.1*x["atr14"]),
rule(8,"breakout_retest","5m 15m","p_close p_prior_high20 p_prior_low20 low high close ema20 rvol20 atr14",
 lambda x:x["p_close"]>x["p_prior_high20"] and abs(x["low"]-x["p_prior_high20"])<=.5*x["atr14"] and x["close"]>max(x["ema20"],x["p_prior_high20"]) and x["rvol20"]>=1,
 lambda x:x["p_close"]<x["p_prior_low20"] and abs(x["high"]-x["p_prior_low20"])<=.5*x["atr14"] and x["close"]<min(x["ema20"],x["p_prior_low20"]) and x["rvol20"]>=1),
]

RULES += [
rule(9,"range_expansion","5m","atr14_percentile100 rvol20 close open body_fraction",
 lambda x:x["atr14_percentile100"]>=80 and x["rvol20"]>=1.5 and x["body_fraction"]>=.6 and x["close"]>x["open"],
 lambda x:x["atr14_percentile100"]>=80 and x["rvol20"]>=1.5 and x["body_fraction"]>=.6 and x["close"]<x["open"]),
rule(10,"inside_bar_breakout","5m 15m","p_inside high low p_high p_low close rvol20",
 lambda x:x["p_inside"]==1 and x["close"]>x["p_high"] and x["rvol20"]>=1.2,
 lambda x:x["p_inside"]==1 and x["close"]<x["p_low"] and x["rvol20"]>=1.2),
rule(11,"liquidity_sweep","5m","low high close prior_low20 prior_high20 lower_wick_fraction upper_wick_fraction rvol20",
 lambda x:x["low"]<x["prior_low20"]<x["close"] and x["lower_wick_fraction"]>=.5 and x["rvol20"]>=1.2,
 lambda x:x["high"]>x["prior_high20"]>x["close"] and x["upper_wick_fraction"]>=.5 and x["rvol20"]>=1.2),
rule(12,"false_breakout","5m 15m","low high close prior_low20 prior_high20 rsi_bullish_divergence rsi_bearish_divergence",
 lambda x:x["low"]<x["prior_low20"]<x["close"] and x["rsi_bullish_divergence"]==1,
 lambda x:x["high"]>x["prior_high20"]>x["close"] and x["rsi_bearish_divergence"]==1),
rule(13,"momentum_exhaustion","15m","rsi14 macd_bullish_divergence macd_bearish_divergence",
 lambda x:x["rsi14"]<=35 and x["macd_bullish_divergence"]==1,
 lambda x:x["rsi14"]>=65 and x["macd_bearish_divergence"]==1),
rule(14,"mean_reversion","5m 15m","rsi14 bb20_percent_b adx14",
 lambda x:x["rsi14"]<=30 and x["bb20_percent_b"]<0 and x["adx14"]<20,
 lambda x:x["rsi14"]>=70 and x["bb20_percent_b"]>1 and x["adx14"]<20),
rule(15,"vwap_reclaim","5m","close p_close utc_day_vwap p_utc_day_vwap rvol20 ema9",
 lambda x:x["p_close"]<=x["p_utc_day_vwap"] and x["close"]>max(x["utc_day_vwap"],x["ema9"]) and x["rvol20"]>=1.2,
 lambda x:x["p_close"]>=x["p_utc_day_vwap"] and x["close"]<min(x["utc_day_vwap"],x["ema9"]) and x["rvol20"]>=1.2),
rule(16,"vwap_deviation","5m","close utc_day_vwap atr14 rsi14",
 lambda x:x["close"]<x["utc_day_vwap"]-2*x["atr14"] and x["rsi14"]<30,
 lambda x:x["close"]>x["utc_day_vwap"]+2*x["atr14"] and x["rsi14"]>70),
rule(19,"position_buildup","5m 15m","rvol20 roc5_pct close p_close frame_oi",
 lambda x:x["frame_oi"]>.5 and x["rvol20"]>=1.3 and x["close"]>x["p_close"] and x["roc5_pct"]>0,
 lambda x:x["frame_oi"]>.5 and x["rvol20"]>=1.3 and x["close"]<x["p_close"] and x["roc5_pct"]<0),
]

RULES += [
rule(23,"volume_accumulation","15m","obv_window p_obv_window cmf20 bb20_width_pct p_bb20_width_pct close p_close",
 lambda x:x["obv_window"]>x["p_obv_window"] and x["cmf20"]>.15 and x["bb20_width_pct"]<x["p_bb20_width_pct"] and x["close"]>x["p_close"],
 lambda x:x["obv_window"]<x["p_obv_window"] and x["cmf20"]<-.15 and x["bb20_width_pct"]<x["p_bb20_width_pct"] and x["close"]<x["p_close"]),
rule(24,"weekend_range","15m 1h","weekend close prior_high20 prior_low20 atr14 rvol20",
 lambda x:x["weekend"]==1 and x["close"]>x["prior_high20"]+.1*x["atr14"] and x["rvol20"]>=1.2,
 lambda x:x["weekend"]==1 and x["close"]<x["prior_low20"]-.1*x["atr14"] and x["rvol20"]>=1.2),
rule(25,"multi_timeframe_alignment","5m","ema9 ema21 macd_histogram f15_ema20 f15_ema50 f1h_ema20 f1h_ema50",
 lambda x:x["ema9"]>x["ema21"] and x["macd_histogram"]>0 and x["f15_ema20"]>x["f15_ema50"] and x["f1h_ema20"]>x["f1h_ema50"],
 lambda x:x["ema9"]<x["ema21"] and x["macd_histogram"]<0 and x["f15_ema20"]<x["f15_ema50"] and x["f1h_ema20"]<x["f1h_ema50"]),
]
RULES.append(rule(21,"sampled_orderflow_momentum","5m","sample_flow_imbalance book_imbalance book_spread_bps close ema9",
 lambda x:x["sample_flow_imbalance"]>=.3 and x["book_imbalance"]>=.2 and 0<x["book_spread_bps"]<=10 and x["close"]>x["ema9"],
 lambda x:x["sample_flow_imbalance"]<=-.3 and x["book_imbalance"]<=-.2 and 0<x["book_spread_bps"]<=10 and x["close"]<x["ema9"]))
RULES += [
rule(20,"relative_funding_reversal","1h","funding_prior_z funding_latest_z close ema9",
 lambda x:x["funding_prior_z"]<=-2 and x["funding_latest_z"]>x["funding_prior_z"]+.5 and x["close"]>x["ema9"],
 lambda x:x["funding_prior_z"]>=2 and x["funding_latest_z"]<x["funding_prior_z"]-.5 and x["close"]<x["ema9"]),
rule(22,"mark_index_basis_convergence","5m","basis_bps basis_prior_bps index_return_pct mark_return_pct sample_flow_imbalance",
 lambda x:x["basis_prior_bps"]<=-5 and x["basis_prior_bps"]<x["basis_bps"]<0 and x["mark_return_pct"]>x["index_return_pct"]>0 and x["sample_flow_imbalance"]>=.3,
 lambda x:x["basis_prior_bps"]>=5 and 0<x["basis_bps"]<x["basis_prior_bps"] and x["mark_return_pct"]<x["index_return_pct"]<0 and x["sample_flow_imbalance"]<=-.3)]
RULES += [
rule(26,"directional_index_cross","15m","plus_di14 minus_di14 p_plus_di14 p_minus_di14 adx14 close ema20",
 lambda x:x["plus_di14"]>x["minus_di14"] and x["p_plus_di14"]<=x["p_minus_di14"] and x["adx14"]>=20 and x["close"]>x["ema20"],
 lambda x:x["minus_di14"]>x["plus_di14"] and x["p_minus_di14"]<=x["p_plus_di14"] and x["adx14"]>=20 and x["close"]<x["ema20"]),
rule(27,"money_flow_recovery","5m","mfi14 p_mfi14 rsi14 close p_close adx14",
 lambda x:x["p_mfi14"]<=20<x["mfi14"] and x["rsi14"]<45 and x["close"]>x["p_close"] and x["adx14"]<25,
 lambda x:x["p_mfi14"]>=80>x["mfi14"] and x["rsi14"]>55 and x["close"]<x["p_close"] and x["adx14"]<25),
rule(28,"ichimoku_conversion_base_cross","1h","tenkan9 kijun26 p_tenkan9 p_kijun26 close ichimoku_span_b_unshifted",
 lambda x:x["p_tenkan9"]<=x["p_kijun26"] and x["tenkan9"]>x["kijun26"] and x["close"]>max(x["tenkan9"],x["ichimoku_span_b_unshifted"]),
 lambda x:x["p_tenkan9"]>=x["p_kijun26"] and x["tenkan9"]<x["kijun26"] and x["close"]<min(x["tenkan9"],x["ichimoku_span_b_unshifted"])),
rule(29,"long_channel_volume_breakout","1h","close donchian55_prior_high donchian55_prior_low rvol20 atr14 ema50",
 lambda x:x["close"]>max(x["donchian55_prior_high"]+.2*x["atr14"],x["ema50"]) and x["rvol20"]>=1.5,
 lambda x:x["close"]<min(x["donchian55_prior_low"]-.2*x["atr14"],x["ema50"]) and x["rvol20"]>=1.5),
rule(30,"rolling_vwap_flow_reclaim","15m","close p_close rolling_vwap20 p_rolling_vwap20 cmf20 ema20",
 lambda x:x["p_close"]<=x["p_rolling_vwap20"] and x["close"]>max(x["rolling_vwap20"],x["ema20"]) and x["cmf20"]>.1,
 lambda x:x["p_close"]>=x["p_rolling_vwap20"] and x["close"]<min(x["rolling_vwap20"],x["ema20"]) and x["cmf20"]<-.1),
]
RULES += [
rule(31,"keltner_trend_reentry","15m","ema20 ema50 low high close p_close p_keltner20_mid keltner20_mid macd_histogram",
 lambda x:x["ema20"]>x["ema50"] and x["p_close"]<x["p_keltner20_mid"] and x["low"]<=x["keltner20_mid"]<x["close"] and x["macd_histogram"]>0,
 lambda x:x["ema20"]<x["ema50"] and x["p_close"]>x["p_keltner20_mid"] and x["high"]>=x["keltner20_mid"]>x["close"] and x["macd_histogram"]<0),
rule(32,"cci_momentum_breakout","5m","cci20 p_cci20 rvol20 close prior_high10 prior_low10",
 lambda x:x["p_cci20"]<=100<x["cci20"] and x["rvol20"]>=1.5 and x["close"]>x["prior_high10"],
 lambda x:x["p_cci20"]>=-100>x["cci20"] and x["rvol20"]>=1.5 and x["close"]<x["prior_low10"]),
rule(33,"low_volatility_range_release","15m","p_atr14_percentile100 atr14_percentile100 close prior_high50 prior_low50 body_fraction",
 lambda x:0<x["prior_low50"]<x["prior_high50"] and x["p_atr14_percentile100"]<=30 and x["atr14_percentile100"]>60 and x["close"]>x["prior_high50"] and x["body_fraction"]>=.65,
 lambda x:0<x["prior_low50"]<x["prior_high50"] and x["p_atr14_percentile100"]<=30 and x["atr14_percentile100"]>60 and x["close"]<x["prior_low50"] and x["body_fraction"]>=.65),
rule(34,"swing_structure_reversal","15m","low high p_confirmed_swing_low p_confirmed_swing_high close rsi14 cmf20",
 lambda x:0<x["low"]<x["p_confirmed_swing_low"]<x["close"] and x["rsi14"]>40 and x["cmf20"]>0,
 lambda x:x["high"]>x["p_confirmed_swing_high"]>x["close"]>0 and x["rsi14"]<60 and x["cmf20"]<0),
rule(35,"oi_contraction_price_reversal_proxy","5m","frame_oi p_close close open lower_wick_fraction upper_wick_fraction rvol20",
 lambda x:x["frame_oi"]<=-.5 and x["close"]>max(x["open"],x["p_close"]) and x["lower_wick_fraction"]>=.45 and x["rvol20"]>=1.4,
 lambda x:x["frame_oi"]<=-.5 and x["close"]<min(x["open"],x["p_close"]) and x["upper_wick_fraction"]>=.45 and x["rvol20"]>=1.4),
]
RULES += [
rule(36,"rsi_trend_exhaustion_reentry","15m","p_rsi14 rsi14 close p_close upper_wick_fraction lower_wick_fraction adx14",
 lambda x:x["p_rsi14"]<=25<x["rsi14"] and x["close"]>x["p_close"] and x["lower_wick_fraction"]>=.4 and x["adx14"]>=20,
 lambda x:x["p_rsi14"]>=75>x["rsi14"] and x["close"]<x["p_close"] and x["upper_wick_fraction"]>=.4 and x["adx14"]>=20),
rule(37,"divergence_momentum_turn","1h","rsi_bullish_divergence rsi_bearish_divergence macd_histogram p_macd_histogram close ema9",
 lambda x:x["rsi_bullish_divergence"]==1 and x["p_macd_histogram"]<x["macd_histogram"]<0 and x["close"]>x["ema9"],
 lambda x:x["rsi_bearish_divergence"]==1 and x["p_macd_histogram"]>x["macd_histogram"]>0 and x["close"]<x["ema9"]),
rule(38,"higher_trend_stochastic_pullback","5m","f1h_ema20 f1h_ema50 f1h_adx14 close ema20 p_stoch_k14 stoch_k14 stoch_d3",
 lambda x:x["f1h_ema20"]>x["f1h_ema50"] and x["f1h_adx14"]>=22 and x["close"]>x["ema20"] and x["p_stoch_k14"]<=20<x["stoch_k14"]<50 and x["stoch_k14"]>x["stoch_d3"],
 lambda x:x["f1h_ema20"]<x["f1h_ema50"] and x["f1h_adx14"]>=22 and x["close"]<x["ema20"] and x["p_stoch_k14"]>=80>x["stoch_k14"]>50 and x["stoch_k14"]<x["stoch_d3"]),
rule(39,"volume_climax_failed_extension","5m","high low prior_high20 prior_low20 close rvol20 upper_wick_fraction lower_wick_fraction p_rsi14 rsi14",
 lambda x:0<x["low"]<x["prior_low20"]<x["close"] and x["rvol20"]>=2.5 and x["lower_wick_fraction"]>=.55 and x["p_rsi14"]<x["rsi14"]<45,
 lambda x:x["high"]>x["prior_high20"]>x["close"]>0 and x["rvol20"]>=2.5 and x["upper_wick_fraction"]>=.55 and x["p_rsi14"]>x["rsi14"]>55),
rule(40,"volume_backed_macd_acceleration","15m","macd_histogram p_macd_histogram cmf20 rvol20 close p_close ema50",
 lambda x:0<x["p_macd_histogram"]<x["macd_histogram"] and x["cmf20"]>.2 and x["rvol20"]>=1.5 and x["close"]>max(x["p_close"],x["ema50"]),
 lambda x:0>x["p_macd_histogram"]>x["macd_histogram"] and x["cmf20"]<-.2 and x["rvol20"]>=1.5 and x["close"]<min(x["p_close"],x["ema50"])),
]
RULES += [
rule(41,"sample_flow_book_disagreement_reversal","5m","sample_flow_imbalance book_imbalance book_spread_bps close open lower_wick_fraction upper_wick_fraction",
 lambda x:x["sample_flow_imbalance"]<=-.35 and x["book_imbalance"]>=.25 and 0<x["book_spread_bps"]<=8 and x["close"]>x["open"] and x["lower_wick_fraction"]>=.55,
 lambda x:x["sample_flow_imbalance"]>=.35 and x["book_imbalance"]<=-.25 and 0<x["book_spread_bps"]<=8 and x["close"]<x["open"] and x["upper_wick_fraction"]>=.55),
rule(42,"range_to_trend_transition","15m","p_adx14 adx14 plus_di14 minus_di14 close ema20 ema50 rvol20",
 lambda x:x["p_adx14"]<20<=x["adx14"] and x["plus_di14"]>x["minus_di14"] and x["close"]>x["ema20"]>x["ema50"] and x["rvol20"]>=1.2,
 lambda x:x["p_adx14"]<20<=x["adx14"] and x["minus_di14"]>x["plus_di14"] and x["close"]<x["ema20"]<x["ema50"] and x["rvol20"]>=1.2),
rule(43,"failed_channel_breakout_reentry","15m","p_close p_donchian20_prior_high p_donchian20_prior_low close macd_histogram p_macd_histogram",
 lambda x:0<x["p_close"]<x["p_donchian20_prior_low"]<x["close"]<x["p_donchian20_prior_high"] and x["macd_histogram"]>x["p_macd_histogram"],
 lambda x:x["p_close"]>x["p_donchian20_prior_high"]>x["close"]>x["p_donchian20_prior_low"]>0 and x["macd_histogram"]<x["p_macd_histogram"]),
rule(44,"new_york_volume_trend_impulse","15m","new_york_active close open ema20 rvol20 body_fraction roc5_pct",
 lambda x:x["new_york_active"]==1 and x["close"]>max(x["open"],x["ema20"]) and x["rvol20"]>=2 and x["body_fraction"]>=.7 and x["roc5_pct"]>.3,
 lambda x:x["new_york_active"]==1 and x["close"]<min(x["open"],x["ema20"]) and x["rvol20"]>=2 and x["body_fraction"]>=.7 and x["roc5_pct"]<-.3),
rule(45,"index_led_position_buildup","5m","index_return_pct mark_return_pct basis_bps frame_oi sample_flow_imbalance",
 lambda x:x["index_return_pct"]>=.15 and 0<x["mark_return_pct"]<x["index_return_pct"] and abs(x["basis_bps"])<=15 and x["frame_oi"]>.3 and x["sample_flow_imbalance"]>=.25,
 lambda x:x["index_return_pct"]<=-.15 and 0>x["mark_return_pct"]>x["index_return_pct"] and abs(x["basis_bps"])<=15 and x["frame_oi"]>.3 and x["sample_flow_imbalance"]<=-.25),
]
RULES += [
rule(46,"slow_trend_crossover","4h","ema20 ema50 p_ema20 p_ema50 close ema200 roc20_pct",
 lambda x:x["p_ema20"]<=x["p_ema50"] and x["ema20"]>x["ema50"] and x["close"]>x["ema200"] and x["roc20_pct"]>0,
 lambda x:x["p_ema20"]>=x["p_ema50"] and x["ema20"]<x["ema50"] and x["close"]<x["ema200"] and x["roc20_pct"]<0),
rule(47,"position_buildup_pullback_reclaim","5m","frame_oi sample_flow_imbalance book_spread_bps low high close ema9 ema21 p_close",
 lambda x:x["frame_oi"]>.5 and x["sample_flow_imbalance"]>=.4 and 0<x["book_spread_bps"]<=8 and x["ema9"]>x["ema21"] and x["low"]<=x["ema21"]<x["close"] and x["close"]>x["p_close"],
 lambda x:x["frame_oi"]>.5 and x["sample_flow_imbalance"]<=-.4 and 0<x["book_spread_bps"]<=8 and x["ema9"]<x["ema21"] and x["high"]>=x["ema21"]>x["close"] and x["close"]<x["p_close"]),
rule(48,"rolling_vwap_cci_exhaustion","15m","close p_close rolling_vwap20 atr14 cci20 p_cci20 adx14",
 lambda x:x["atr14"]>0 and x["close"]<x["rolling_vwap20"]-x["atr14"] and x["p_cci20"]<=-150<x["cci20"] and x["close"]>x["p_close"] and x["adx14"]<20,
 lambda x:x["atr14"]>0 and x["close"]>x["rolling_vwap20"]+x["atr14"] and x["p_cci20"]>=150>x["cci20"] and x["close"]<x["p_close"] and x["adx14"]<20),
rule(49,"daily_level_retest_with_flow","15m","previous_day_high previous_day_low p_close close low high atr14 cmf20",
 lambda x:x["atr14"]>0 and x["p_close"]>x["previous_day_high"] and abs(x["low"]-x["previous_day_high"])<=.3*x["atr14"] and x["close"]>x["previous_day_high"] and x["cmf20"]>.15,
 lambda x:x["atr14"]>0 and 0<x["p_close"]<x["previous_day_low"] and abs(x["high"]-x["previous_day_low"])<=.3*x["atr14"] and x["close"]<x["previous_day_low"] and x["cmf20"]<-.15),
rule(50,"return_dispersion_momentum_expansion","5m","return_std20_pct p_return_std20_pct roc5_pct close prior_high10 prior_low10 rvol20",
 lambda x:0<x["p_return_std20_pct"] and x["return_std20_pct"]>=1.3*x["p_return_std20_pct"] and x["roc5_pct"]>.4 and x["close"]>x["prior_high10"] and x["rvol20"]>=1.5,
 lambda x:0<x["p_return_std20_pct"] and x["return_std20_pct"]>=1.3*x["p_return_std20_pct"] and x["roc5_pct"]<-.4 and x["close"]<x["prior_low10"] and x["rvol20"]>=1.5),
]
DEFERRED={
 "B17":("short_squeeze","validated funding units and liquidation/positioning evidence"),
 "B18":("long_liquidation","independent liquidation-flow feed"),
}

def inputs(market,frame):
    item=market["frames"].get(frame,{})
    if item.get("status")!="ready": return {}
    d={**market.get("context",{}),**item["features"]}
    d.update({k:v for k,v in item["candle"].items() if k in ("open","high","low","close","volume")})
    d.update({"p_"+k:v for k,v in item["previous_features"].items()})
    d.update({"p_"+k:v for k,v in item["previous_candle"].items() if k in ("open","high","low","close")})
    d.update(flow_inputs(market.get("quotes",{})))
    d["p_inside"]=item.get("previous_inside")
    d["weekend"]=int(item.get("prior_20_all_weekend",False))
    d["frame_oi"]=d.get("oi_change_pct_"+frame)
    for f,prefix in (("15m","f15_"),("1h","f1h_")):
        other=market["frames"].get(f,{})
        if other.get("status")=="ready":
            d.update({prefix+k:v for k,v in other["features"].items()})
    return d

def scan_btc(snapshot):
    market=snapshot["markets"]["BTCUSD"]
    results=[]; signals=[]
    for r in RULES:
        for f in r.frames:
            result=evaluate(r,inputs(market,f))
            row={"id":r.id,"name":r.name,"frame":f,**result}
            results.append(row)
            for side in result.get("directions",[]):
                signals.append({"id":r.id,"frame":f,"direction":side,"closed_at":market["frames"][f]["closed_at"]})
    return {"symbol":"BTCUSD","as_of":snapshot["as_of"],"signal_rule":"one_of_n","trigger_ai":bool(signals),
            "signals":signals,"results":results,"deferred":DEFERRED,"ai_dispatched":False,"orders_submitted":0}
