"""Learning reports are isolated from all execution and decision control."""
from pathlib import Path
from contextlib import closing
from time import time
import sqlite3,json
from tradebot.signal_learning_v3 import evaluate_event,aggregate
from tradebot.strategy_profiles_v3 import build as build_profiles
from tradebot.regime_learning_v3 import regime_statistics,advisory
from tradebot.market_data_v3 import MARKETS
from tradebot.research_collector_v3 import atomic_json

def ro(path): return sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True,timeout=10)

def tick(root,*,now=None):
    root=Path(root); now=int(time()) if now is None else now
    result={"mode":"research_only","checked_at":now,"markets":{},"scanner_control":False,
            "orders_submitted":0,"ai_requests":0,"warning":"Forward price observations exclude fees, slippage, funding and actual fills. Overlapping observations are not independent trades."}
    profile_rows={}; profile_coverage={}
    with closing(ro(root/"opportunities-v3.sqlite")) as events,closing(ro(root/"market-v3.sqlite")) as market:
        events.execute("BEGIN"); market.execute("BEGIN")
        def bars(s,a,b):
            return [json.loads(x[0]) for x in market.execute("SELECT payload FROM samples WHERE symbol=? AND series='candle:5m' AND stamp>=? AND stamp<? ORDER BY stamp",(s,a,b))]
        for s in MARKETS:
            rows=[]; rejected=0
            # Bound report size and explicitly expose coverage.
            raw=events.execute("SELECT payload FROM events WHERE symbol=? ORDER BY as_of DESC,event_id DESC LIMIT 501",(s,)).fetchall()
            for x in raw[:500]:
                try: rows.extend(evaluate_event(json.loads(x[0]),bars,now=now))
                except (ValueError,TypeError,KeyError): rejected+=1
            profile_rows[s]=rows
            profile_coverage[s]={"event_count":min(len(raw),500),"truncated":len(raw)>500,"rejected_events":rejected}
            regimes=regime_statistics(rows)
            result["markets"][s]={"event_count":min(len(raw),500),"truncated":len(raw)>500,"rejected_events":rejected,
                "signal_horizon_rows":len(rows),"observed":sum(r["status"]=="observed" for r in rows),
                "pending":sum(r["status"]=="pending" for r in rows),"missing":sum(r["status"]=="missing_candles" for r in rows),
                "strategy_statistics":aggregate(rows),"regime_statistics":regimes,
                "ai_learning_context":advisory(s,regimes,as_of=now),"verified_trade_outcomes":None,
                "trade_outcome_status":"signed_settlement_integration_pending"}
    try:
        atomic_json(root/"strategy-profiles-v3.json",build_profiles(root,profile_rows,now=now,coverage_by_market=profile_coverage))
        result["strategy_profiles_status"]="ready"
    except Exception as e:
        result["strategy_profiles_status"]="unavailable:"+type(e).__name__
    try:
        from tradebot.decision_quality_v3 import report as decision_quality
        decision_quality(root,now=now)
        result["decision_quality_status"]="ready"
    except Exception as e:
        result["decision_quality_status"]="unavailable:"+type(e).__name__
    try:
        from tradebot.decision_experience_v3 import tick as experience_tick
        experience_tick(root,now=now)
        result["decision_experience_status"]="ready"
    except Exception as e:
        result["decision_experience_status"]="unavailable:"+type(e).__name__
    atomic_json(root/"learning-status-v3.json",result)
    return result

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--directory",type=Path,required=True)
    r=tick(p.parse_args().directory)
    print(json.dumps({s:{k:v[k] for k in ("event_count","observed","pending","missing","rejected_events")} for s,v in r["markets"].items()}))
