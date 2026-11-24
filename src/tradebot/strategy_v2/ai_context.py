"""Build a bounded AI market-context package from a validated 1-of-10 event.

This prepares model INPUT, never an AI call, broker order or risk override.
"""
from hashlib import sha256
from math import isfinite

from tradebot.multi_strategy_signals import _features, STRATEGIES
from tradebot.signal_ai_router import AI_ROUTE, _event_id


def build_model_context(event, completed_candles):
    if (not isinstance(event, dict)
            or event.get("status") != "ready_for_ai_evaluation"
            or event.get("dispatch_ai") is not True
            or event.get("execution_authorized") is not False
            or event.get("requires_fresh_broker_and_risk_checks") is not True
            or event.get("symbol") not in AI_ROUTE
            or event.get("model") != AI_ROUTE.get(event.get("symbol"))
            or type(event.get("candle_time")) is not int
            or event.get("event_id") != _event_id(
                event.get("symbol"), event.get("candle_time"))):
        raise ValueError("untrusted_model_signal_event")
    symbol, stamp = event["symbol"], event["candle_time"]
    signals = event.get("signals")
    if not isinstance(signals, list) or not 1 <= len(signals) <= 20:
        raise ValueError("no_valid_model_signal")
    unique = set()
    directions = set()
    for entry in signals:
        if not isinstance(entry, dict):
            raise ValueError("untrusted_model_signal")
        strategy, side = entry.get("strategy_id"), entry.get("direction")
        score = entry.get("score")
        if (strategy not in STRATEGIES or side not in ("LONG", "SHORT")
                or type(score) is not int or not 60 <= score <= 95
                or entry.get("strength") != ("strong" if score>=80 else "moderate")
                or entry.get("signal_id") != sha256(
                    f"{symbol}:{stamp}:{strategy}:{side}".encode()).hexdigest()[:20]):
            raise ValueError("untrusted_model_signal")
        identity=(strategy,side)
        if identity in unique:
            raise ValueError("duplicate_model_signal")
        unique.add(identity)
        directions.add(side)
    if event.get("conflicting_directions") is not (len(directions) > 1):
        raise ValueError("invalid_direction_conflict")
    features = _features(completed_candles, symbol, stamp+300)
    if features["time"] != stamp:
        raise ValueError("model_signal_candle_mismatch")
    keys = {
        "last_close":"close", "ema20":"ema20", "ema50":"ema50",
        "ema200":"ema200", "rsi14":"rsi", "adx14":"adx",
        "plus_di14":"plus_di", "minus_di14":"minus_di",
        "macd_histogram":"macd", "stochastic14":"stoch",
        "relative_volume20":"rvol", "atr14":"atr",
        "bollinger_lower":"bb_low", "bollinger_middle":"bb_mid",
        "bollinger_upper":"bb_high", "session_vwap":"vwap",
        "prior_20_high":"range_high", "prior_20_low":"range_low",
    }
    indicators = {}
    for label, key in keys.items():
        value = features[key]
        if value is not None and (not isinstance(value,(int,float))
                                  or not isfinite(value)):
            raise ValueError("invalid_model_indicator")
        indicators[label] = round(value,6) if value is not None else None
    return {
        "schema":"tradebot2.indicator_signal.v2",
        "event_id":event["event_id"],
        "symbol":symbol, "closed_candle_time":stamp,
        "model_route":AI_ROUTE[symbol],
        "trigger_rule":"one_qualifying_detector_suffices",
        "score_interpretation":"uncalibrated_setup_heuristic_not_win_probability",
        "conflicting_directions":len(directions)>1,
        "signals":[{"strategy_id":entry["strategy_id"],
                    "direction":entry["direction"],
                    "score":entry["score"],
                    "strength":entry["strength"]}
                   for entry in signals],
        "indicators":indicators,
        "decision_required":"evaluate_opportunity_not_execute",
        "constraints":{
            "broker_quote_and_account_verification_required":True,
            "risk_governor_required":True,
            "protective_stop_and_target_required":True,
            "trade_authorized":False,
        },
    }

