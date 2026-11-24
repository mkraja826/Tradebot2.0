"""Fixed-rule historical replay, no AI calls, brokerage, or parameter tuning."""
from collections import defaultdict
from contextlib import closing
from statistics import mean
from pathlib import Path
import sqlite3,json,time
from tradebot.feature_snapshot_v3 import snapshot
from tradebot.market_data_v3 import MARKETS,FRAMES,normalize
from tradebot.bitcoin_strategies_v3 import scan_btc
from tradebot.gold_strategies_v3 import scan_gold
from tradebot.research_collector_v3 import atomic_json

HOLD=900
COST_BPS=10
def outcome(db,s,stamp,side,*,cost_bps=COST_BPS):
    # Enter at next 5m open, never at the signal close.
    start=stamp+300; end=start+HOLD
    raw=db.execute("SELECT payload FROM samples WHERE symbol=? AND series='candle:5m' AND stamp>=? AND stamp<? ORDER BY stamp",(s,start,end))
    try: rows=normalize([json.loads(r[0]) for r in raw],"5m",as_of=end,count=HOLD//300)
    except ValueError: return None
    entry=rows[0]["open"]; exit=rows[-1]["close"]; sign=1 if side=="LONG" else -1
    gross=100*sign*(exit-entry)/entry
    return {"entry_at":start,"exit_at":end,"gross_return_pct":gross,"net_cost_scenario_pct":gross-cost_bps/100}

def summarize(rows):
    vals=[r["net_cost_scenario_pct"] for r in rows]
    total=peak=dd=0.0
    for v in vals:
        total+=v; peak=max(peak,total); dd=max(dd,peak-total)
    return {"samples":len(vals),"positive_after_cost":sum(v>0 for v in vals),
        "mean_after_cost_pct":mean(vals) if vals else None,
        "additive_sequence_drawdown_pct_points":dd if vals else None,
        "sample_status":"small_sample" if len(vals)<30 else "descriptive_only"}

def replay(database,*,start,end,cutoff):
    if not start<cutoff<end or any(x%300 for x in (start,end,cutoff)) or end-start>86400:
        raise ValueError("invalid_pilot_window")
    report={"mode":"historical_fixed_rule_pilot","start":start,"end":end,"holdout_start":cutoff,
        "roundtrip_cost_assumption_bps":COST_BPS,"holding_minutes":HOLD//60,"markets":{},
        "execution_authorized":False,"orders_submitted":0,"paid_ai_requests":0,
        "warning":"Hypothetical fixed notional returns, no leverage, funding, stop/target execution or portfolio simulation. Chronological holdout, not tuned walk-forward."}
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        for s,scan in zip(MARKETS,(scan_btc,scan_gold)):
            stats=defaultdict(lambda:{"evaluated":0,"unavailable":0,"signals":0,"missing_outcome":0,"overlap_or_embargo":0,"development":[],"holdout":[]})
            last_exit={}
            for t in range(start,end,300):
                a=scan(snapshot(database,t,symbols=(s,)))
                for r in a["results"]:
                    if t%FRAMES[r["frame"]]: continue
                    k=(r["id"],r["frame"]); g=stats[k]; g["evaluated"]+=1
                    if r["status"]=="unavailable": g["unavailable"]+=1; continue
                    sides=r.get("directions",[]); g["signals"]+=len(sides)
                    if len(sides)!=1: continue
                    finish=t+300+HOLD
                    if finish>end or t<cutoff<finish or t+300<last_exit.get(k,0):
                        g["overlap_or_embargo"]+=1; continue
                    o=outcome(db,s,t,sides[0])
                    if o is None: g["missing_outcome"]+=1; continue
                    last_exit[k]=o["exit_at"]; g["development" if t<cutoff else "holdout"].append(o)
            report["markets"][s]={"deferred":a["deferred"],"rules":[dict(rule_id=k[0],frame=k[1],**{n:(summarize(v) if isinstance(v,list) else v) for n,v in g.items()}) for k,g in sorted(stats.items())]}
    return report
