"""Read-only strategy evidence. Observations are not executed trades or causal attribution."""
import math,sqlite3
from collections import Counter,defaultdict
from contextlib import closing
from pathlib import Path
from statistics import mean
from .regime import FAMILIES
from .research import HORIZONS,TOLERANCE
from .performance import stats
from tradebot.bitcoin_strategies_v3 import RULES as BTC, DEFERRED as BTC_DEFERRED
from tradebot.gold_strategies_v3 import RULES as GOLD, DEFERRED as GOLD_DEFERRED
VERSION="strategy-evidence-v1"
COST_BPS=15

def summarize(rows,horizon):
    # Select non-overlapping windows BEFORE looking at outcomes. Across frames and sides.
    # Reserve full horizon plus allowed observation lag, even for missed/pending windows.
    counts=Counter();selected=Counter();returns=[];until=-1
    for ident,entry,status,exit_us,value in sorted(rows,key=lambda r:(r[1],r[0])):
        counts[status]+=1
        if type(entry) is not int or entry<0:continue
        if entry<until:counts["overlap_excluded"]+=1;continue
        until=entry+(horizon+TOLERANCE)*1000000
        selected[status]+=1
        if status=="observed" and type(exit_us) is int and entry+horizon*1000000<=exit_us<=until and type(value) in (int,float) and math.isfinite(value):
            returns.append(value-COST_BPS)
        elif status=="observed":selected["invalid_observation"]+=1
    return {"horizon_s":horizon,"raw_counts":dict(counts),"selected_counts":dict(selected),"valid_samples":len(returns),
        "mean_net_bps":mean(returns) if returns else None,"positive_rate":sum(r>0 for r in returns)/len(returns) if returns else None}

def build(symbol,observations,performance):
    prefix="B" if symbol=="BTCUSD" else "G"
    registry={r.id:r for r in (BTC if prefix=="B" else GOLD)}
    deferred=BTC_DEFERRED if prefix=="B" else GOLD_DEFERRED
    groups=defaultdict(list)
    for ident,rule,horizon,entry,status,exit_us,value in observations:
        if rule in FAMILIES and rule.startswith(prefix) and horizon in HORIZONS:
            groups[rule,horizon].append((ident,entry,status,exit_us,value))
    co=performance.get("active_rule_cooccurrence") or {}
    rules=[]
    for ident in sorted(k for k in FAMILIES if k.startswith(prefix)):
        r=registry.get(ident)
        rules.append({"id":ident,"name":r.name if r else deferred.get(ident,(None,None))[0],"missing_dependency":deferred.get(ident,(None,None))[1],"family":FAMILIES[ident],"implementation":"implemented" if r else "deferred",
            "frames":list(r.frames) if r else [],"actual_cooccurrence":co.get(ident),"research":[summarize(groups[ident,h],h) for h in HORIZONS]})
    exact=defaultdict(list)
    # Each attributed episode belongs to one exact signal set only, no duplicated P&L.
    for e in performance.get("recent_episodes",[]):
        if e.get("decision_id"):
            exact[tuple(sorted(set(e.get("active_rules",[]))))].append(e)
    return {"version":VERSION,"symbol":symbol,"status":"observed","execution_effect":"none","assumed_cost_bps":COST_BPS,
        "rules":rules,"implemented":len(registry),"deferred":len(rules)-len(registry),"exact_entry_rule_sets":[{"rules":list(k),**stats(v)} for k,v in sorted(exact.items())],
        "limitations":["Exact rule sets use recent attributed episodes only. Co-occurrence counts overlap and do not establish causal contribution.",
        "Research is fixed-horizon mark-price movement net of assumed 15 bps, not actual fills, leverage, brackets or AI outcomes.",
        "Nonoverlap within each rule/horizon only; cross-rule samples are correlated. No ranking or strategy change based on small samples."]}

def report(root,symbol,performance):
    try:
        with closing(sqlite3.connect((Path(root)/"signal_research.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            rows=db.execute("SELECT id,rule_id,horizon_s,entry_us,status,exit_us,return_bps FROM observations WHERE symbol=?",(symbol,)).fetchall()
        return build(symbol,rows,performance)
    except (sqlite3.Error,ValueError,TypeError,KeyError,AttributeError,ArithmeticError):
        return {"version":VERSION,"symbol":symbol,"status":"unavailable","execution_effect":"none"}
