"""Chronological market-regime research; no live weights or execution."""
import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from .regime import FAMILIES
from .regime_performance import category
from .research import HORIZONS,TOLERANCE
from .trade_intelligence import sql

VERSION="regime-intelligence-v1"
SYMBOLS=("BTCUSD","XAUTUSD")
COSTS=(5,15,30)

def valid_price(v):
    return type(v) in (int,float) and math.isfinite(v) and v>0

def windows(rows,horizon,split,end):
    """Select before inspecting outcomes. Purge intervals crossing the split."""
    span=(horizon+TOLERANCE)*1000000
    until=-1;counts=Counter();selected=[]
    for row in sorted(rows,key=lambda r:(r[0],r[1])):
        entry,ident,rule,side,regime,vol,closed,status,exit_us,entry_px,exit_px,ret=row
        if entry>=end or entry+span>end:
            counts["outside_mature_window"]+=1;continue
        if entry<split<entry+span:
            counts["purged_split_boundary"]+=1;continue
        if entry<until:
            counts["overlap_excluded"]+=1;continue
        until=entry+span
        period="development" if entry<split else "holdout"
        counts[period+"_selected"]+=1
        if status!="observed":
            counts[period+"_"+str(status)]+=1;continue
        if (type(exit_us) is not int or not entry+horizon*1000000<=exit_us<=entry+span
            or not valid_price(entry_px) or not valid_price(exit_px) or type(ret) not in (int,float)
            or not math.isfinite(ret)):
            counts["invalid_observation"]+=1;continue
        expected=(exit_px/entry_px-1)*10000*(1 if side=="LONG" else -1)
        if not math.isfinite(expected) or not math.isclose(ret,expected,rel_tol=1e-8,abs_tol=1e-6):
            counts["return_mismatch"]+=1;continue
        if abs(ret)>=1000:
            counts["large_return_review"]+=1;continue
        selected.append((period,regime,vol,side,ret))
    return selected,dict(counts)

def metrics(values):
    if not values:return {"samples":0,"mean_gross_bps":None,"median_gross_bps":None,"cost_scenarios":[]}
    return {"samples":len(values),"mean_gross_bps":mean(values),"median_gross_bps":median(values),
        "cost_scenarios":[{"assumed_cost_bps":c,"mean_net_bps":mean([v-c for v in values]),
            "positive_rate":sum(v>c for v in values)/len(values)} for c in COSTS]}

def build(symbol,rows,split,end):
    if symbol not in SYMBOLS or type(split) is not int or type(end) is not int or not 0<split<end:
        raise ValueError("invalid symbol or chronological UTC cutoff")
    prefix="B" if symbol=="BTCUSD" else "G"
    groups=defaultdict(list);coverage=Counter();bad=0
    for ident,rule,frame,side,regime,vol,closed,entry,entry_px,horizon,status,exit_us,exit_px,ret in rows:
        if (not isinstance(ident,str) or not isinstance(rule,str) or not rule.startswith(prefix)
            or rule not in FAMILIES or side not in ("LONG","SHORT") or horizon not in HORIZONS
            or type(entry) is not int or type(closed) is not int or closed<=0 or closed*1000000>entry):
            bad+=1;continue
        r,v=category(regime,vol);coverage[r,v]+=1
        normalized=(entry,ident,rule,side,r,v,closed,status,exit_us,entry_px,exit_px,ret)
        for level,name in (("rule",rule),("family",FAMILIES[rule])):
            groups[level,name,horizon].append(normalized)
    result=[]
    for (level,name,h),items in sorted(groups.items()):
        selected,counts=windows(items,h,split*1000000,end*1000000)
        cohort=defaultdict(lambda:defaultdict(list))
        for period,r,v,side,value in selected:
            cohort[r,v,side][period].append(value)
        strata=[]
        for (r,v,side),periods in sorted(cohort.items()):
            dev=metrics(periods["development"]);hold=metrics(periods["holdout"])
            strata.append({"regime":r,"volatility":v,"direction":side,"development":dev,"holdout":hold,
                "comparison":"descriptive_both_periods" if dev["samples"] and hold["samples"] else "missing_one_period",
                "causal_validation":False})
        result.append({"level":level,"id":name,"horizon_s":h,"selection_counts":counts,"strata":strata})
    return {"version":VERSION,"symbol":symbol,"status":"observed","execution_effect":"none",
        "cutoffs":{"development_end_utc":split,"holdout_end_utc":end},
        "coverage":[{"regime":r,"volatility":v,"journal_rows":n} for (r,v),n in sorted(coverage.items())],
        "invalid_records":bad,"groups":result,"validation":"retrospective_chronological_comparison_only",
        "limitations":["Recorded signal-time regimes; reversing markets are not a separate archived regime.",
        "Nonoverlap selection precedes outcome filtering within each rule/family and horizon; cohorts across groups may correlate.",
        "Full permitted observation windows crossing the split are purged. Holdout is retrospective unless cutoffs were registered beforehand.",
        "Mark-price directional returns are not executable fills; cost scenarios are hypothetical.",
        "Large returns flagged at 1000 bps are excluded from this diagnostic only; inspect their source before using them.",
        "No statistical significance claim, calibrated probability, strategy ranking, live weights or execution changes."]}

def report(root,symbol,split,end):
    if symbol not in SYMBOLS or type(split) is not int or type(end) is not int or not 0<split<end:
        raise ValueError("invalid symbol or cutoff")
    rows=sql(Path(root)/"signal_research.sqlite",
        """SELECT id,rule_id,frame,side,regime,volatility,closed_at,entry_us,entry,horizon_s,status,exit_us,exit,return_bps
        FROM observations WHERE symbol=? AND entry_us<?""",(symbol,end*1000000))
    if rows is None:return {"version":VERSION,"symbol":symbol,"status":"unavailable","execution_effect":"none","groups":[]}
    return build(symbol,rows,split,end)

def main():
    p=argparse.ArgumentParser();p.add_argument("--data-dir",default="/var/lib/recover-trading/demo")
    p.add_argument("--symbol",required=True,choices=SYMBOLS)
    p.add_argument("--split",required=True,type=int);p.add_argument("--end",required=True,type=int)
    a=p.parse_args();print(json.dumps(report(Path(a.data_dir)/a.symbol,a.symbol,a.split,a.end),allow_nan=False,indent=2))
if __name__=="__main__":main()
