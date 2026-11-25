"""Read-only stratified research using regime recorded at signal/decision time."""
import json,math,sqlite3
from collections import Counter,defaultdict
from contextlib import closing
from pathlib import Path
from statistics import mean
from .regime import FAMILIES
from .research import HORIZONS,TOLERANCE
from .performance import stats
VERSION="regime-performance-v1"
COST_BPS=15
REGIMES=("trending","ranging","mixed","unknown")
VOLS=("normal","high","unknown")

def category(r,v):
    return (r if r in REGIMES else "unknown",v if v in VOLS else "unknown")

def stratify(rows,horizon):
    # Select nonoverlapping windows across all regimes and sides before examining
    # outcomes, using the full allowed horizon plus observation lag.
    counts=defaultdict(Counter);selected=defaultdict(Counter);returns=defaultdict(list)
    until=-1
    for ident,entry,status,exit_us,value,regime,vol in sorted(rows,key=lambda r:(r[1],r[0])):
        k=category(regime,vol);counts[k][status]+=1
        if type(entry) is not int or entry<0:counts[k]["invalid_entry"]+=1;continue
        if entry<until:counts[k]["overlap_excluded"]+=1;continue
        until=entry+(horizon+TOLERANCE)*1000000
        selected[k][status]+=1
        if status=="observed" and type(exit_us) is int and entry+horizon*1000000<=exit_us<=until and type(value) in (int,float) and math.isfinite(value):
            returns[k].append(value-COST_BPS)
        elif status=="observed":selected[k]["invalid_observation"]+=1
    return [{"regime":r,"volatility":v,"horizon_s":horizon,"raw_counts":dict(counts[r,v]),"selected_counts":dict(selected[r,v]),
        "valid_samples":len(returns[r,v]),"mean_net_bps":mean(returns[r,v]) if returns[r,v] else None,
        "positive_rate":sum(x>0 for x in returns[r,v])/len(returns[r,v]) if returns[r,v] else None}
        for r,v in sorted(counts)]

def build(symbol,observations,episodes,contexts):
    prefix={"BTCUSD":"B","XAUTUSD":"G"}[symbol]
    groups=defaultdict(list);coverage=Counter()
    for ident,rule,horizon,entry,status,exit_us,value,r,v in observations:
        if not isinstance(rule,str) or not rule.startswith(prefix) or rule not in FAMILIES or horizon not in HORIZONS:continue
        regime,vol=category(r,v);coverage[regime,vol,status]+=1
        row=(ident,entry,status,exit_us,value,regime,vol)
        for level,name in (("rule",rule),("family",FAMILIES[rule])):
            groups[level,name,horizon].append(row)
    research=[]
    for (level,name,h),rows in sorted(groups.items()):
        for row in stratify(rows,h):
            research.append({"level":level,"id":name,**row})
    actual=defaultdict(list);exact=defaultdict(list);seen=set()
    for ep in episodes:
        i=ep.get("decision_id")
        if not i or i in seen or ep.get("attribution")!="single_recover_entry_order":continue
        seen.add(i)
        c=contexts.get(i) or {}
        if c.get("symbol")!=symbol:c={}
        r=(c.get("direction_engine") or {}).get("regime") or {}
        k=category(r.get("regime"),r.get("volatility"))
        actual[k].append(ep)
        exact[(*k,tuple(sorted(set(ep.get("active_rules",[])))) )].append(ep)
    return {"version":VERSION,"symbol":symbol,"status":"observed","execution_effect":"none","assumed_cost_bps":COST_BPS,
        "coverage":[{"regime":r,"volatility":v,"status":s,"count":n} for (r,v,s),n in sorted(coverage.items())],
        "research":research,"actual":[{"regime":r,"volatility":v,**stats(e)} for (r,v),e in sorted(actual.items())],
        "exact_rule_sets":[{"regime":r,"volatility":v,"rules":list(ids),**stats(e)} for (r,v,ids),e in sorted(exact.items())],
        "observed_regimes":sorted({r for r,v,s in coverage}),"observed_volatility":sorted({v for r,v,s in coverage}),
        "validation":"descriptive_only","limitations":["Signal-time regime is not retrospectively inferred; volatility is a separate axis, not a mutually exclusive regime.",
          "Rule and family tables select nonoverlap separately across regimes; family rows are not averages of rules. Cross-rule and cross-family samples can correlate.",
          "Mark-price fixed-horizon observations less assumed 15 bps; not fills, actual P&L, or evidence of profitable trading.",
          "Actual outcomes use recent reconciled attributed episodes and archived decision-time regime only; funding excluded. Missing context is unknown.",
          "No ranking, statistical validation or live weight changes."]}

def report(root,symbol,performance):
    root=Path(root)
    try:
        with closing(sqlite3.connect((root/"signal_research.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            rows=db.execute("SELECT id,rule_id,horizon_s,entry_us,status,exit_us,return_bps,regime,volatility FROM observations WHERE symbol=?",(symbol,)).fetchall()
        with closing(sqlite3.connect((root/"decisions.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            contexts={i:json.loads(c) for i,c in db.execute("SELECT id,context FROM decisions WHERE symbol=?",(symbol,))}
        return build(symbol,rows,performance.get("recent_episodes",[]),contexts)
    except (sqlite3.Error,ValueError,KeyError,TypeError,AttributeError,ArithmeticError):
        return {"version":VERSION,"symbol":symbol,"status":"unavailable","execution_effect":"none"}
