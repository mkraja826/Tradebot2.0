"""Gold-specific candidate rules; all thresholds are uncalibrated research settings."""
from tradebot.strategy_rules_v3 import Rule,evaluate

def rule(i,name,frames,fields,long,short):
    return Rule(f"G{i:02}",name,tuple(frames.split()),fields,long,short)

RULES=[
rule(1,"established_trend","15m 1h","ema20 ema50 adx14 close",
 lambda x:x["ema20"]>x["ema50"] and x["adx14"]>=23 and x["close"]>x["ema20"],
 lambda x:x["ema20"]<x["ema50"] and x["adx14"]>=23 and x["close"]<x["ema20"]),
rule(2,"major_directional_trend","1h 4h","ema50 ema200 macd_histogram",
 lambda x:x["ema50"]>x["ema200"] and x["macd_histogram"]>0,
 lambda x:x["ema50"]<x["ema200"] and x["macd_histogram"]<0),
rule(3,"fibonacci_trend_pullback","15m","ema20 fib_direction fib_500 low high close rsi14 atr14",
 lambda x:x["fib_direction"]==1 and abs(x["low"]-x["fib_500"])<=.5*x["atr14"] and x["close"]>max(x["fib_500"],x["ema20"]) and 45<=x["rsi14"]<=65,
 lambda x:x["fib_direction"]==-1 and abs(x["high"]-x["fib_500"])<=.5*x["atr14"] and x["close"]<min(x["fib_500"],x["ema20"]) and 35<=x["rsi14"]<=55),
rule(4,"trend_resumption","15m","supertrend_direction atr14 close p_close prior_high10 prior_low10",
 lambda x:x["supertrend_direction"]==1 and x["p_close"]<=x["prior_high10"] and x["close"]>x["prior_high10"]+.1*x["atr14"],
 lambda x:x["supertrend_direction"]==-1 and x["p_close"]>=x["prior_low10"] and x["close"]<x["prior_low10"]-.1*x["atr14"]),
rule(5,"london_open_breakout","5m 15m","london_opening asian_pre_london_high asian_pre_london_low close atr14 rvol20",
 lambda x:x["london_opening"]==1 and x["close"]>x["asian_pre_london_high"]+.1*x["atr14"] and x["rvol20"]>=1.2,
 lambda x:x["london_opening"]==1 and x["close"]<x["asian_pre_london_low"]-.1*x["atr14"] and x["rvol20"]>=1.2),
rule(6,"new_york_open_breakout","5m 15m","new_york_opening london_pre_ny_high london_pre_ny_low close new_york_vwap rvol20",
 lambda x:x["new_york_opening"]==1 and x["close"]>max(x["london_pre_ny_high"],x["new_york_vwap"]) and x["rvol20"]>=1.2,
 lambda x:x["new_york_opening"]==1 and x["close"]<min(x["london_pre_ny_low"],x["new_york_vwap"]) and x["rvol20"]>=1.2),
rule(7,"session_overlap_momentum","5m 15m","overlap active_session_vwap close adx14 macd_histogram",
 lambda x:x["overlap"]==1 and x["close"]>x["active_session_vwap"] and x["adx14"]>=23 and x["macd_histogram"]>0,
 lambda x:x["overlap"]==1 and x["close"]<x["active_session_vwap"] and x["adx14"]>=23 and x["macd_histogram"]<0),
rule(8,"asian_range_reversal","5m 15m","tokyo_active asian_prior_high asian_prior_low high low close stoch_k14 adx14",
 lambda x:x["tokyo_active"]==1 and x["low"]<=x["asian_prior_low"]<x["close"] and x["stoch_k14"]<25 and x["adx14"]<20,
 lambda x:x["tokyo_active"]==1 and x["high"]>=x["asian_prior_high"]>x["close"] and x["stoch_k14"]>75 and x["adx14"]<20),
]

RULES += [
rule(9,"previous_day_breakout","15m","close previous_day_high previous_day_low atr14 rvol20",
 lambda x:x["close"]>x["previous_day_high"]+.1*x["atr14"] and x["rvol20"]>=1.2,
 lambda x:x["close"]<x["previous_day_low"]-.1*x["atr14"] and x["rvol20"]>=1.2),
rule(10,"weekly_level_breakout","1h","close previous_week_high previous_week_low ema50",
 lambda x:x["close"]>max(x["previous_week_high"],x["ema50"]),
 lambda x:x["close"]<min(x["previous_week_low"],x["ema50"])),
rule(11,"daily_pivot_rejection","5m 15m","previous_day_s1 previous_day_r1 low high close lower_wick_fraction upper_wick_fraction",
 lambda x:x["low"]<=x["previous_day_s1"]<x["close"] and x["lower_wick_fraction"]>=.45,
 lambda x:x["high"]>=x["previous_day_r1"]>x["close"] and x["upper_wick_fraction"]>=.45),
rule(12,"fibonacci_reversal","15m 1h","fib_direction fib_618 low high close atr14 rsi_bullish_divergence rsi_bearish_divergence",
 lambda x:x["fib_direction"]==1 and abs(x["low"]-x["fib_618"])<=.5*x["atr14"] and x["close"]>x["fib_618"] and x["rsi_bullish_divergence"]==1,
 lambda x:x["fib_direction"]==-1 and abs(x["high"]-x["fib_618"])<=.5*x["atr14"] and x["close"]<x["fib_618"] and x["rsi_bearish_divergence"]==1),
rule(13,"support_resistance_bounce","5m 15m","prior_low20 prior_high20 low high close rsi14 lower_wick_fraction upper_wick_fraction atr14",
 lambda x:abs(x["low"]-x["prior_low20"])<=.4*x["atr14"] and x["close"]>x["prior_low20"] and x["rsi14"]<40 and x["lower_wick_fraction"]>=.4,
 lambda x:abs(x["high"]-x["prior_high20"])<=.4*x["atr14"] and x["close"]<x["prior_high20"] and x["rsi14"]>60 and x["upper_wick_fraction"]>=.4),
rule(14,"range_mean_reversion","5m 15m","bb20_percent_b stoch_k14 adx14",
 lambda x:x["bb20_percent_b"]<0 and x["stoch_k14"]<20 and x["adx14"]<20,
 lambda x:x["bb20_percent_b"]>1 and x["stoch_k14"]>80 and x["adx14"]<20),
rule(15,"session_vwap_reversion","5m 15m","close active_session_vwap atr14 rsi14",
 lambda x:x["close"]<x["active_session_vwap"]-1.5*x["atr14"] and x["rsi14"]<30,
 lambda x:x["close"]>x["active_session_vwap"]+1.5*x["atr14"] and x["rsi14"]>70),
rule(16,"volatility_contraction_release","15m","p_atr14_percentile100 p_bb20_width_pct bb20_width_pct close prior_high10 prior_low10",
 lambda x:x["p_atr14_percentile100"]<=25 and x["bb20_width_pct"]>x["p_bb20_width_pct"] and x["close"]>x["prior_high10"],
 lambda x:x["p_atr14_percentile100"]<=25 and x["bb20_width_pct"]>x["p_bb20_width_pct"] and x["close"]<x["prior_low10"]),
rule(17,"compression_breakout","15m","p_bb20_upper p_bb20_lower p_keltner_upper p_keltner_lower close keltner_upper keltner_lower roc5_pct rvol20",
 lambda x:x["p_bb20_upper"]<x["p_keltner_upper"] and x["p_bb20_lower"]>x["p_keltner_lower"] and x["close"]>x["keltner_upper"] and x["roc5_pct"]>0 and x["rvol20"]>=1.2,
 lambda x:x["p_bb20_upper"]<x["p_keltner_upper"] and x["p_bb20_lower"]>x["p_keltner_lower"] and x["close"]<x["keltner_lower"] and x["roc5_pct"]<0 and x["rvol20"]>=1.2),
]

RULES += [
rule(18,"daily_broad_dollar_confirmation","4h","broad_dollar_5obs_pct close ema20 ema50 macd_histogram",
 lambda x:x["broad_dollar_5obs_pct"]<=-.3 and x["close"]>x["ema20"]>x["ema50"] and x["macd_histogram"]>0,
 lambda x:x["broad_dollar_5obs_pct"]>=.3 and x["close"]<x["ema20"]<x["ema50"] and x["macd_histogram"]<0),
rule(19,"daily_real_nominal_yield_confirmation","4h","nominal_yield_5obs_bp real_yield_5obs_bp close ema20 macd_histogram",
 lambda x:x["nominal_yield_5obs_bp"]<=-5 and x["real_yield_5obs_bp"]<=-5 and x["close"]>x["ema20"] and x["macd_histogram"]>0,
 lambda x:x["nominal_yield_5obs_bp"]>=5 and x["real_yield_5obs_bp"]>=5 and x["close"]<x["ema20"] and x["macd_histogram"]<0)]

RULES.append(rule(22,"fomc_post_statement_price_reaction","15m","fomc_post_statement close open ema9 rvol20 body_fraction",
 lambda x:x["fomc_post_statement"]==1 and x["close"]>max(x["open"],x["ema9"]) and x["rvol20"]>=1.5 and x["body_fraction"]>=.6,
 lambda x:x["fomc_post_statement"]==1 and x["close"]<min(x["open"],x["ema9"]) and x["rvol20"]>=1.5 and x["body_fraction"]>=.6))
RULES.append(rule(23,"daily_volatility_weekly_stress_momentum","4h","vix_daily vix_5obs_change stress_weekly stress_weekly_change close ema20 ema50 macd_histogram",
 lambda x:x["vix_daily"]>=25 and x["vix_5obs_change"]>=3 and x["stress_weekly"]>0 and x["stress_weekly_change"]>0 and x["close"]>x["ema20"]>x["ema50"] and x["macd_histogram"]>0,
 lambda x:0<x["vix_daily"]<=20 and x["vix_5obs_change"]<=-3 and x["stress_weekly"]<0 and x["stress_weekly_change"]<0 and x["close"]<x["ema20"]<x["ema50"] and x["macd_histogram"]<0))
RULES.append(rule(24,"indicative_spot_divergence_reversal","5m","indicative_gold_basis_bps delta_quote_spread_bps close p_close ema9 rsi14",
 lambda x:x["indicative_gold_basis_bps"]<=-20 and 0<x["delta_quote_spread_bps"]<=5 and x["close"]>max(x["p_close"],x["ema9"]) and x["rsi14"]<55,
 lambda x:x["indicative_gold_basis_bps"]>=20 and 0<x["delta_quote_spread_bps"]<=5 and x["close"]<min(x["p_close"],x["ema9"]) and x["rsi14"]>45))
RULES += [
rule(26,"trend_stochastic_cross","15m","stoch_k14 stoch_d3 p_stoch_k14 p_stoch_d3 close ema20 ema50",
 lambda x:x["p_stoch_k14"]<=x["p_stoch_d3"] and x["stoch_k14"]>x["stoch_d3"] and 0<x["stoch_k14"]<40 and x["close"]>x["ema20"]>x["ema50"],
 lambda x:x["p_stoch_k14"]>=x["p_stoch_d3"] and x["stoch_k14"]<x["stoch_d3"] and 60<x["stoch_k14"]<100 and x["close"]<x["ema20"]<x["ema50"]),
rule(27,"cci_range_recovery","15m","cci20 p_cci20 adx14 close p_close",
 lambda x:x["p_cci20"]<=-100<x["cci20"] and x["adx14"]<20 and x["close"]>x["p_close"],
 lambda x:x["p_cci20"]>=100>x["cci20"] and x["adx14"]<20 and x["close"]<x["p_close"]),
rule(28,"daily_pivot_momentum_cross","1h","previous_day_pivot p_close close rvol20 macd_histogram",
 lambda x:x["p_close"]<=x["previous_day_pivot"]<x["close"] and x["rvol20"]>=1.2 and x["macd_histogram"]>0,
 lambda x:x["p_close"]>=x["previous_day_pivot"]>x["close"] and x["rvol20"]>=1.2 and x["macd_histogram"]<0),
rule(29,"supertrend_flip_directional","1h","supertrend_direction p_supertrend_direction plus_di14 minus_di14 adx14",
 lambda x:x["p_supertrend_direction"]==-1 and x["supertrend_direction"]==1 and x["plus_di14"]>x["minus_di14"] and x["adx14"]>=20,
 lambda x:x["p_supertrend_direction"]==1 and x["supertrend_direction"]==-1 and x["minus_di14"]>x["plus_di14"] and x["adx14"]>=20),
rule(30,"money_flow_trend_acceleration","15m","cmf20 p_cmf20 mfi14 close ema20 roc5_pct",
 lambda x:x["p_cmf20"]<=0<x["cmf20"] and 55<=x["mfi14"]<80 and x["close"]>x["ema20"] and x["roc5_pct"]>0,
 lambda x:x["p_cmf20"]>=0>x["cmf20"] and 20<x["mfi14"]<=45 and x["close"]<x["ema20"] and x["roc5_pct"]<0),
]
RULES += [
rule(31,"london_session_pullback","15m","london_active close low high ema20 ema50 rsi14 p_rsi14",
 lambda x:x["london_active"]==1 and x["ema20"]>x["ema50"] and x["low"]<=x["ema20"]<x["close"] and x["p_rsi14"]<=50<x["rsi14"],
 lambda x:x["london_active"]==1 and x["ema20"]<x["ema50"] and x["high"]>=x["ema20"]>x["close"] and x["p_rsi14"]>=50>x["rsi14"]),
rule(32,"ny_pivot_second_level_rejection","15m","new_york_active previous_day_s2 previous_day_r2 low high close lower_wick_fraction upper_wick_fraction rsi14",
 lambda x:x["new_york_active"]==1 and 0<x["low"]<x["previous_day_s2"]<x["close"] and x["lower_wick_fraction"]>=.5 and x["rsi14"]<40,
 lambda x:x["new_york_active"]==1 and x["high"]>x["previous_day_r2"]>x["close"]>0 and x["upper_wick_fraction"]>=.5 and x["rsi14"]>60),
rule(33,"bollinger_midline_trend_reclaim","1h","close p_close bb20_mid p_bb20_mid ema50 adx14 roc5_pct",
 lambda x:x["p_close"]<=x["p_bb20_mid"] and x["close"]>max(x["bb20_mid"],x["ema50"]) and x["adx14"]>=22 and x["roc5_pct"]>0,
 lambda x:x["p_close"]>=x["p_bb20_mid"] and x["close"]<min(x["bb20_mid"],x["ema50"]) and x["adx14"]>=22 and x["roc5_pct"]<0),
rule(34,"fib_shallow_trend_retest","1h","fib_direction fib_382 low high close atr14 ema20 macd_histogram",
 lambda x:x["fib_direction"]==1 and x["atr14"]>0 and abs(x["low"]-x["fib_382"])<=.25*x["atr14"] and x["close"]>max(x["fib_382"],x["ema20"]) and x["macd_histogram"]>0,
 lambda x:x["fib_direction"]==-1 and x["atr14"]>0 and abs(x["high"]-x["fib_382"])<=.25*x["atr14"] and x["close"]<min(x["fib_382"],x["ema20"]) and x["macd_histogram"]<0),
rule(35,"range_oscillator_reentry","15m","bb20_percent_b p_bb20_percent_b mfi14 adx14 close p_close",
 lambda x:x["p_bb20_percent_b"]<0<=x["bb20_percent_b"]<.5 and x["mfi14"]<35 and x["adx14"]<20 and x["close"]>x["p_close"],
 lambda x:x["p_bb20_percent_b"]>1>=x["bb20_percent_b"]>.5 and x["mfi14"]>65 and x["adx14"]<20 and x["close"]<x["p_close"]),
]
RULES += [
rule(36,"session_vwap_exhaustion_recovery","5m","active_session_vwap close p_close low high atr14 p_rsi14 rsi14",
 lambda x:x["atr14"]>0 and x["low"]<x["active_session_vwap"]-1.5*x["atr14"] and x["p_rsi14"]<=30<x["rsi14"] and x["close"]>x["p_close"] and x["close"]<x["active_session_vwap"],
 lambda x:x["atr14"]>0 and x["high"]>x["active_session_vwap"]+1.5*x["atr14"] and x["p_rsi14"]>=70>x["rsi14"] and x["close"]<x["p_close"] and x["close"]>x["active_session_vwap"]),
rule(37,"macd_divergence_pivot_recovery","1h","macd_bullish_divergence macd_bearish_divergence previous_day_pivot close p_close ema9",
 lambda x:x["macd_bullish_divergence"]==1 and x["p_close"]<=x["previous_day_pivot"]<x["close"] and x["close"]>x["ema9"],
 lambda x:x["macd_bearish_divergence"]==1 and x["p_close"]>=x["previous_day_pivot"]>x["close"] and x["close"]<x["ema9"]),
rule(38,"higher_trend_session_pullback","15m","f4h_ema20 f4h_ema50 f4h_adx14 active_session_vwap low high close p_rsi14 rsi14",
 lambda x:x["f4h_ema20"]>x["f4h_ema50"] and x["f4h_adx14"]>=22 and x["low"]<=x["active_session_vwap"]<x["close"] and x["p_rsi14"]<=45<x["rsi14"],
 lambda x:x["f4h_ema20"]<x["f4h_ema50"] and x["f4h_adx14"]>=22 and x["high"]>=x["active_session_vwap"]>x["close"] and x["p_rsi14"]>=55>x["rsi14"]),
rule(39,"volume_climax_pivot_rejection","15m","previous_day_s1 previous_day_r1 low high close rvol20 lower_wick_fraction upper_wick_fraction mfi14",
 lambda x:0<x["low"]<x["previous_day_s1"]<x["close"] and x["rvol20"]>=2 and x["lower_wick_fraction"]>=.55 and x["mfi14"]<35,
 lambda x:x["high"]>x["previous_day_r1"]>x["close"]>0 and x["rvol20"]>=2 and x["upper_wick_fraction"]>=.55 and x["mfi14"]>65),
rule(40,"obv_directional_trend_confirmation","1h","obv_window p_obv_window close p_close ema20 ema50 cmf20 rvol20",
 lambda x:x["obv_window"]>x["p_obv_window"] and x["close"]>max(x["p_close"],x["ema20"]) and x["ema20"]>x["ema50"] and x["cmf20"]>.15 and x["rvol20"]>=1.3,
 lambda x:x["obv_window"]<x["p_obv_window"] and x["close"]<min(x["p_close"],x["ema20"]) and x["ema20"]<x["ema50"] and x["cmf20"]<-.15 and x["rvol20"]>=1.3),
]
RULES += [
rule(41,"sampled_flow_session_breakout","5m","sample_flow_imbalance book_imbalance book_spread_bps overlap close prior_high10 prior_low10 rvol20",
 lambda x:x["overlap"]==1 and x["sample_flow_imbalance"]>=.35 and x["book_imbalance"]>=.15 and 0<x["book_spread_bps"]<=5 and x["close"]>x["prior_high10"] and x["rvol20"]>=1.3,
 lambda x:x["overlap"]==1 and x["sample_flow_imbalance"]<=-.35 and x["book_imbalance"]<=-.15 and 0<x["book_spread_bps"]<=5 and x["close"]<x["prior_low10"] and x["rvol20"]>=1.3),
rule(42,"trend_to_range_reversal","1h","p_adx14 adx14 rsi14 p_rsi14 bb20_percent_b close p_close",
 lambda x:x["p_adx14"]>=25 and x["adx14"]<25 and x["p_rsi14"]<=35<x["rsi14"] and 0<=x["bb20_percent_b"]<.35 and x["close"]>x["p_close"],
 lambda x:x["p_adx14"]>=25 and x["adx14"]<25 and x["p_rsi14"]>=65>x["rsi14"] and .65<x["bb20_percent_b"]<=1 and x["close"]<x["p_close"]),
rule(43,"weekly_level_failed_breakout","1h","previous_week_high previous_week_low p_close close lower_wick_fraction upper_wick_fraction cmf20",
 lambda x:0<x["p_close"]<x["previous_week_low"]<x["close"]<x["previous_week_high"] and x["lower_wick_fraction"]>=.4 and x["cmf20"]>0,
 lambda x:x["p_close"]>x["previous_week_high"]>x["close"]>x["previous_week_low"]>0 and x["upper_wick_fraction"]>=.4 and x["cmf20"]<0),
rule(44,"overlap_session_vwap_impulse","15m","overlap active_session_vwap close open atr14 body_fraction rvol20 ema9",
 lambda x:x["overlap"]==1 and x["atr14"]>0 and x["open"]<=x["active_session_vwap"] and x["close"]>max(x["active_session_vwap"]+.2*x["atr14"],x["ema9"]) and x["body_fraction"]>=.65 and x["rvol20"]>=1.5,
 lambda x:x["overlap"]==1 and x["atr14"]>0 and x["open"]>=x["active_session_vwap"] and x["close"]<min(x["active_session_vwap"]-.2*x["atr14"],x["ema9"]) and x["body_fraction"]>=.65 and x["rvol20"]>=1.5),
rule(45,"joint_daily_macro_trend_pullback","4h","broad_dollar_5obs_pct real_yield_5obs_bp close low high ema20 p_rsi14 rsi14",
 lambda x:x["broad_dollar_5obs_pct"]<=-.3 and x["real_yield_5obs_bp"]<=-5 and x["low"]<=x["ema20"]<x["close"] and x["p_rsi14"]<=45<x["rsi14"],
 lambda x:x["broad_dollar_5obs_pct"]>=.3 and x["real_yield_5obs_bp"]>=5 and x["high"]>=x["ema20"]>x["close"] and x["p_rsi14"]>=55>x["rsi14"]),
]
RULES += [
rule(46,"weekly_midpoint_momentum_cross","4h","previous_week_high previous_week_low close p_close ema20 macd_histogram",
 lambda x:0<x["previous_week_low"]<x["previous_week_high"] and x["p_close"]<=(x["previous_week_high"]+x["previous_week_low"])/2<x["close"] and x["close"]>x["ema20"] and x["macd_histogram"]>0,
 lambda x:0<x["previous_week_low"]<x["previous_week_high"] and x["p_close"]>=(x["previous_week_high"]+x["previous_week_low"])/2>x["close"] and x["close"]<x["ema20"] and x["macd_histogram"]<0),
rule(47,"asian_session_trend_impulse","15m","tokyo_active london_active close open rolling_vwap20 ema20 ema50 body_fraction rvol20",
 lambda x:x["tokyo_active"]==1 and x["london_active"]==0 and x["close"]>max(x["open"],x["rolling_vwap20"]) and x["ema20"]>x["ema50"] and x["body_fraction"]>=.65 and x["rvol20"]>=1.5,
 lambda x:x["tokyo_active"]==1 and x["london_active"]==0 and x["close"]<min(x["open"],x["rolling_vwap20"]) and x["ema20"]<x["ema50"] and x["body_fraction"]>=.65 and x["rvol20"]>=1.5),
rule(48,"indicative_reference_near_parity_breakout","5m","indicative_gold_basis_bps delta_quote_spread_bps close prior_high10 prior_low10 atr14 rvol20 cmf20",
 lambda x:abs(x["indicative_gold_basis_bps"])<=10 and 0<x["delta_quote_spread_bps"]<=5 and x["atr14"]>0 and x["close"]>x["prior_high10"]+.1*x["atr14"] and x["rvol20"]>=1.5 and x["cmf20"]>.1,
 lambda x:abs(x["indicative_gold_basis_bps"])<=10 and 0<x["delta_quote_spread_bps"]<=5 and x["atr14"]>0 and x["close"]<x["prior_low10"]-.1*x["atr14"] and x["rvol20"]>=1.5 and x["cmf20"]<-.1),
rule(49,"volatility_real_yield_alignment","4h","vix_daily vix_5obs_change real_yield_5obs_bp close ema50 plus_di14 minus_di14",
 lambda x:x["vix_daily"]>=25 and x["vix_5obs_change"]>=3 and x["real_yield_5obs_bp"]<=-10 and x["close"]>x["ema50"] and x["plus_di14"]>x["minus_di14"],
 lambda x:0<x["vix_daily"]<=20 and x["vix_5obs_change"]<=-3 and x["real_yield_5obs_bp"]>=10 and x["close"]<x["ema50"] and x["minus_di14"]>x["plus_di14"]),
rule(50,"higher_trend_channel_breakout","15m","f4h_ema20 f4h_ema50 f4h_macd_histogram close prior_high20 prior_low20 atr14 rvol20",
 lambda x:x["f4h_ema20"]>x["f4h_ema50"] and x["f4h_macd_histogram"]>0 and x["atr14"]>0 and x["close"]>x["prior_high20"]+.15*x["atr14"] and x["rvol20"]>=1.3,
 lambda x:x["f4h_ema20"]<x["f4h_ema50"] and x["f4h_macd_histogram"]<0 and x["atr14"]>0 and x["close"]<x["prior_low20"]-.15*x["atr14"] and x["rvol20"]>=1.3),
]
DEFERRED={
 "G20":("inflation_release_reaction","actual CPI and consensus forecast"),
 "G21":("employment_release_reaction","actual NFP and consensus forecast"),
 "G25":("weekend_reference_reopen","verified reference-market trading calendar and fresh gold reference"),
}

def inputs(market,frame):
    item=market["frames"].get(frame,{})
    if item.get("status")!="ready": return {}
    d={**market.get("context",{}),**item["features"],**item.get("gold_context",{})}
    d.update({k:v for k,v in item["candle"].items() if k in ("open","high","low","close","volume")})
    from tradebot.trade_flow_v3 import inputs as flow_inputs
    d.update(flow_inputs(market.get("quotes",{})))
    d["fomc_post_statement"]=item.get("fomc_post_statement")
    d.update({"p_"+k:v for k,v in item["previous_features"].items()})
    d.update({"p_"+k:v for k,v in item["previous_candle"].items() if k in ("open","high","low","close")})
    other=market["frames"].get("4h",{})
    if other.get("status")=="ready" and type(other.get("closed_at")) is int and type(item.get("closed_at")) is int and 0<=item["closed_at"]-other["closed_at"]<14400:
        d.update({"f4h_"+k:v for k,v in other["features"].items()})
    return d

def scan_gold(snapshot):
    market=snapshot["markets"]["XAUTUSD"]
    results=[]; signals=[]
    for r in RULES:
        for f in r.frames:
            result=evaluate(r,inputs(market,f))
            results.append({"id":r.id,"name":r.name,"frame":f,**result})
            for side in result.get("directions",[]):
                signals.append({"id":r.id,"frame":f,"direction":side,"closed_at":market["frames"][f]["closed_at"]})
    return {"symbol":"XAUTUSD","as_of":snapshot["as_of"],"signal_rule":"one_of_n","trigger_ai":bool(signals),
            "signals":signals,"results":results,"deferred":DEFERRED,"ai_dispatched":False,"orders_submitted":0}
