[redacted potentially sensitive output]

This module never calls an AI provider or mutates broker/trading state.
Use --once (default) from a systemd timer; the next tick retries feed faults.
"""
import json
import time
from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.multi_strategy_signals import scan_completed_5m
from tradebot.signal_ai_router import build_ai_signal_event


def sample_market(broker, symbol, *, as_of):
    if (getattr(broker, "base_url", None) != DEMO_API
            or getattr(broker, "allow_orders", None) is not False):
        raise ValueError("shadow_demo_read_only_broker_required")
    candles=broker.candles(symbol=symbol,resolution="5m",
                           start=as_of-300*300,end=as_of)
    completed=[c for c in candles
               if isinstance(c,dict) and type(c.get("time")) is int
               and c["time"]+300<=as_of]
    completed.sort(key=lambda c:c["time"])
    event=scan_completed_5m(completed[-250:],symbol,as_of=as_of)
    ai=build_ai_signal_event(event)
    return {
        "symbol":symbol,"mode":"SHADOW_NO_AI_NO_ORDERS",
        "candle_time":event["candle_time"],"candidate_count":event["candidate_count"],
        "trigger_ai_if_connected":ai["dispatch_ai"],
        "event_id":ai["event_id"],
        "ai_route":ai.get("model"),"execution_authorized":False,
    }


def run_shadow(*, broker=None, now=None):
    """Public market data only; isolates failures per symbol."""
    client=broker if broker is not None else DeltaDemo(
[redacted potentially sensitive output]
    moment=int(time.time()) if now is None else now
    if type(moment) is not int:
        raise ValueError("shadow_invalid_clock")
    closed_boundary=moment//300*300
    results=[]
    for symbol in ("BTCUSD","XAUTUSD"):
        try:
            results.append(sample_market(client,symbol,as_of=closed_boundary))
        except Exception as exc:
[redacted potentially sensitive output]
            results.append({"symbol":symbol,"mode":"SHADOW_NO_AI_NO_ORDERS",
                            "status":"signal_scan_unavailable",
                            "error_type":type(exc).__name__,
                            "execution_authorized":False})
    return {"read_only":True,"ai_requests":0,"broker_mutations":0,
            "as_of":closed_boundary,"markets":results}


def main():
    print(json.dumps(run_shadow(),sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

