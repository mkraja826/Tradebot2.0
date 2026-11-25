"""Read-only market collection and exact recovered V3 strategy evaluation."""
import argparse
import json
import time
import math
from .macro_feed import collect_context, apply_context
from .direction import direction_for
from collections import Counter
from tradebot.market_data_v3 import MARKETS, FRAMES, collect, public_client
from tradebot.market_store_v3 import MarketStore
from tradebot.market_intelligence_v3 import collect_intelligence
from tradebot.trade_flow_v3 import collect_flow
from tradebot.derivative_context_v3 import SERIES, collect as collect_derivative
from tradebot.gold_reference_v3 import collect as collect_gold_reference
from tradebot.feature_snapshot_v3 import snapshot
from tradebot.bitcoin_strategies_v3 import scan_btc
from tradebot.gold_strategies_v3 import scan_gold

SCANNERS = {"BTCUSD": scan_btc, "XAUTUSD": scan_gold}


def scan_market(store, client, symbol, *, clock=time.time,
                gold_reference=collect_gold_reference, external_context=collect_context, include_context=False):
    if symbol not in MARKETS:
        raise ValueError("Unknown market")
    as_of = int(clock())
    health = {}

    def attempt(label, fn):
        try:
            fn()
        except Exception as exc:
            health[label] = {"status": "unavailable", "reason": type(exc).__name__}
        else:
            health[label] = {"status": "ready"}

    for frame in FRAMES:
        # The recovered snapshot uses longer 5m history for session/weekly context.
        target = (900 if symbol == "XAUTUSD" else 600) if frame == "5m" else (
            180 if symbol == "XAUTUSD" and frame == "1d" else 250)
        def save_frame(frame=frame, target=target):
            result = collect(client, symbol, as_of=as_of, frames=(frame,), count=target)["frames"][frame]
            if result["status"] != "ready" and target > 250:
                result = collect(client, symbol, as_of=as_of, frames=(frame,), count=250)["frames"][frame]
            if result["status"] != "ready":
                health["candle:" + frame] = {"status": "unavailable", "reason": result["reason"]}
                return False
            store.candles(symbol, frame, result["bars"], as_of=as_of)
            health["candle:" + frame] = {"status": "ready", "bars": len(result["bars"])}
            return True
        try:
            save_frame()
        except Exception as exc:
            health["candle:" + frame] = {"status": "unavailable", "reason": type(exc).__name__}

    intelligence = collect_intelligence(client, symbol)
    for name, item in intelligence.items():
        if item["status"] == "ready":
            attempt(name, lambda name=name, item=item: store.intelligence(symbol, name, item["data"]))
        else:
            health[name] = {"status": "unavailable", "reason": "feed_unavailable"}
    attempt("flow", lambda: store.intelligence(symbol, "flow", collect_flow(client, symbol)))
    if symbol == "BTCUSD":
        for kind in SERIES:
            def save_series(kind=kind):
                rows = collect_derivative(client, kind, as_of=as_of)
                if not rows:
                    raise ValueError("empty_derivative_history")
                store.derivative_history(kind, rows, as_of=as_of)
            attempt(kind, save_series)
    else:
        attempt("xau_reference", lambda: store.intelligence(symbol, "xau_reference", gold_reference()))

    refs = {}
    if symbol == "XAUTUSD":
        try:
            refs = external_context()
            health.update({"external:" + k: {"status": v["status"], **({"reason": v["reason"]} if "reason" in v else {})} for k, v in refs.items()})
        except Exception as exc:
            health["external"] = {"status": "unavailable", "reason": type(exc).__name__}
    # Round the snapshot cutoff up so subsecond observations just recorded are included.
    now = math.ceil(clock())
    data = snapshot(store.path, now, symbols=(symbol,), candle_as_of=as_of)
    if symbol == "XAUTUSD":
        apply_context(data, refs, now)
    report = SCANNERS[symbol](data)
    rows = report["results"]
    ids = {r["id"] for r in rows}
    evaluable = {r["id"] for r in rows if r["status"] in ("triggered", "no_signal")}
    report["coverage"] = {
        "implemented_rules": len(ids),
        "evaluable_rules": len(evaluable),
        "unavailable_rules": len(ids - evaluable),
        "deferred_rules": len(report["deferred"]),
        "evaluation_statuses": dict(Counter(r["status"] for r in rows)),
        "missing_features": dict(Counter(k for r in rows for k in r.get("missing", []))),
    }
    report["direction_engine"] = direction_for(report)
    report["trigger_ai"] = report["direction_engine"]["direction"] != "NEUTRAL"
    report["signal_rule"] = "equal-rule-v1"
    report["feed_health"] = health
    report["candle_as_of"] = as_of
    if include_context:
        report["market_context"] = data["markets"][symbol]
    return report


def scan_once(path, *, client=None, symbols=MARKETS, clock=time.time,
              gold_reference=collect_gold_reference, external_context=collect_context, include_context=False):
    store = MarketStore(path)
    client = public_client() if client is None else client
    reports = {}
    for symbol in symbols:
        try:
            reports[symbol] = scan_market(store, client, symbol, clock=clock, gold_reference=gold_reference, external_context=external_context, include_context=include_context)
        except Exception as exc:
            reports[symbol] = {"symbol": symbol, "status": "scan_error", "reason": type(exc).__name__}
    return {"mode": "read_only", "markets": reports, "orders_submitted": 0, "ai_calls": 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", default="data/recover-market.sqlite")
    p.add_argument("--symbol", choices=MARKETS, action="append")
    p.add_argument("--interval", type=float, default=0, help="0 runs once; positive seconds run repeated scans")
    args = p.parse_args()
    if args.interval < 0:
        p.error("interval must be non-negative")
    while True:
        print(json.dumps(scan_once(args.database, symbols=args.symbol or MARKETS), allow_nan=False), flush=True)
        if not args.interval:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
