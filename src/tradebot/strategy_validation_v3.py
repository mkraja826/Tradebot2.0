"""M14 fixed-rule validation with comparable signal overlap and coverage.
No threshold optimization, broker writes, or strategy eligibility changes.
"""
from collections import defaultdict,Counter
from contextlib import closing
from itertools import combinations
from pathlib import Path
from statistics import mean
import sqlite3
from tradebot.advanced_backtest_v3 import HORIZONS,COSTS,handle_signal,metrics,regimes
from tradebot.feature_snapshot_v3 import snapshot
from tradebot.market_data_v3 import MARKETS,FRAMES
from tradebot.bitcoin_strategies_v3 import scan_btc
from tradebot.gold_strategies_v3 import scan_gold

def overlap_update(pairs,results):
    by_frame=defaultdict(list)
    for r in results:
        if r["status"] in ("no_signal","triggered"):
            by_frame[r["frame"]].append((r["id"],set(r.get("directions",[]))))
    for frame,rows in by_frame.items():
        for (a,x),(b,y) in combinations(sorted(rows),2):
            c=pairs[(frame,a,b)]
            c["joint_evaluable"]+=1
            if x or y: c["union"]+=1
            if x and y:
                c["both_active"]+=1
                if x&y: c["same_direction"]+=1
                if any(u!=v for u in x for v in y): c["opposite_direction"]+=1

def overlap_report(pairs):
    return [dict(frame=f,rule_a=a,rule_b=b,**c,
        active_jaccard=c["both_active"]/c["union"],
        same_side_jaccard=c["same_direction"]/c["union"])
        for (f,a,b),c in sorted(pairs.items()) if c["union"]]

def group_profile(rows):
    out=metrics(rows)
    out["sample_status"]="insufficient_sample" if len(rows)<30 else "descriptive_only"
    if rows and all("favorable_excursion_pct" in r for r in rows):
        out["mean_favorable_excursion_pct"]=mean(r["favorable_excursion_pct"] for r in rows)
        out["mean_adverse_excursion_pct"]=mean(r["adverse_excursion_pct"] for r in rows)
    buckets=defaultdict(list)
    for r in rows:
        for dimension,value in r["regime"].items(): buckets[(dimension,value)].append(r["gross_return_pct"])
    out["regime_profiles"]=[dict(dimension=d,value=v,samples=len(xs),mean_after_10bps_pct=mean(xs)-.1,
         positive_after_10bps=sum(x>.1 for x in xs),sample_status="insufficient_sample" if len(xs)<30 else "descriptive_only")
         for (d,v),xs in sorted(buckets.items())]
    return out

def replay(database,*,start,end):
    if type(start) is not int or type(end) is not int or start>=end or start%300 or end%300 or end-start>12*3600:
        raise ValueError("invalid_window")
    out={"mode":"fixed_rule_chronological_validation","start":start,"end":end,
         "horizons_minutes":HORIZONS,"roundtrip_cost_bps":COSTS,"markets":{},
         "strategy_eligibility_changed":False,"execution_authorized":False,"orders_submitted":0,"paid_ai_requests":0,
         "warning":"Candle-only replay; missing macro/order-flow inputs stay unavailable. No tuned parameters, portfolio P&L, actual fills, funding or leverage."}
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        for s,scan in zip(MARKETS,(scan_btc,scan_gold)):
            groups=defaultdict(list);last={};counts=Counter();coverage=defaultdict(Counter);pairs=defaultdict(Counter)
            for t in range(start,end,300):
                snap=snapshot(database,t,symbols=(s,)); market=snap["markets"][s]; a=scan(snap)
                eligible=[r for r in a["results"] if t%FRAMES[r["frame"]]==0]
                for r in eligible:
                    c=coverage[(r["id"],r["frame"])]
                    c["evaluations"]+=1;c[r["status"]]+=1
                    for key in r.get("missing",[]): c["missing:"+key]+=1
                overlap_update(pairs,eligible)
                for sig in a["signals"]:
                    if sig["closed_at"]!=t: continue
                    counts["signals"]+=1
                    handle_signal(db,s,t,end,market,sig,groups,last,counts)
            out["markets"][s]={"coverage":[dict(rule_id=r,frame=f,**c) for (r,f),c in sorted(coverage.items())],
                "deferred":a["deferred"],"scenario_counts":dict(counts),
                "groups":[dict(rule_id=k[0],frame=k[1],side=k[2],horizon=k[3],scenario=k[4],**group_profile(v)) for k,v in sorted(groups.items())],
                "regimes":regimes(groups),"signal_overlap":overlap_report(pairs),
                "comparable_pairs":len(pairs)}
    return out
