"""Validate and route one scanner event to AI; never authorize trade execution."""
from collections.abc import Mapping
from hashlib import sha256

from tradebot.multi_strategy_signals import STRATEGIES, MARKETS

AI_ROUTE = {"BTCUSD":"GPT-6", "XAUTUSD":"DeepSeek"}


def _event_id(symbol, candle_time):
    """Stable across simultaneous signals; at most one AI dispatch per candle."""
    return sha256(f"signal-v1:{symbol}:{candle_time}".encode()).hexdigest()[:24]


def build_ai_signal_event(scan, *, processed=()):
    """Fail closed for malformed or untrusted signals, leave all order gates intact.

    The caller must persist event IDs atomically before issuing an actual AI
    request. This module neither persists nor invokes models or exchanges.
    """
    if not isinstance(scan, Mapping):
        raise ValueError("invalid_signal_scan")
    symbol = scan.get("symbol")
    stamp = scan.get("candle_time")
    if (symbol not in MARKETS or type(stamp) is not int or stamp%300
            or scan.get("source")!="completed_5m_local_1_of_10"
            or scan.get("execution_authorized") is not False
            or type(scan.get("trigger_ai")) is not bool):
        raise ValueError("untrusted_signal_snapshot")
    signals = scan.get("signals")
    if not isinstance(signals, list) or len(signals)>20:
        raise ValueError("invalid_signal_candidates")
    if scan.get("candidate_count") != len(signals):
        raise ValueError("invalid_signal_count")
    if scan["trigger_ai"] != bool(signals):
        raise ValueError("invalid_signal_trigger")
    sides=set()
    identities=set()
    safe_signals=[]
    for signal in signals:
        if not isinstance(signal, Mapping):
            raise ValueError("invalid_signal")
        sid=signal.get("strategy_id")
        side=signal.get("direction")
        score=signal.get("score")
        if (sid not in STRATEGIES or side not in ("LONG","SHORT")
                or type(score) is not int or not 60<=score<=95
                or signal.get("candle_time")!=stamp
                or signal.get("trade_authorized") is not False
                or signal.get("strength") != ("strong" if score>=80 else "moderate")):
            raise ValueError("invalid_signal_evidence")
        identity=f"{symbol}:{stamp}:{sid}:{side}"
        expected=sha256(identity.encode()).hexdigest()[:20]
        if signal.get("signal_id") != expected or identity in identities:
            raise ValueError("signal_identity_invalid_or_duplicate")
        identities.add(identity)
        sides.add(side)
        safe_signals.append({
            "strategy_id":sid, "direction":side,
            "score":score,"strength":signal["strength"],
            "signal_id":expected,
        })
    expected_hint=next(iter(sides)) if len(sides)==1 else None
    if (scan.get("conflicting_directions") is not (len(sides)>1)
            or scan.get("direction_hint")!=expected_hint):
        raise ValueError("invalid_signal_conflict_state")
    key=_event_id(symbol,stamp)
    if not signals:
        return {"status":"no_qualifying_signal","dispatch_ai":False,
                "event_id":key,"execution_authorized":False}
    if key in processed:
        return {"status":"duplicate_candle_event","dispatch_ai":False,
                "event_id":key,"execution_authorized":False}
    return {
        "status":"ready_for_ai_evaluation",
        "dispatch_ai":True,"event_id":key,"model":AI_ROUTE[symbol],
        "symbol":symbol,"candle_time":stamp,
        "signals":safe_signals,"conflicting_directions":len(sides)>1,
        "signal_rule":"one_of_ten",
        "execution_authorized":False,
        "requires_fresh_broker_and_risk_checks":True,
    }

