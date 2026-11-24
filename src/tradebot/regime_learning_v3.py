"""Descriptive, uncalibrated regime labels from frozen signal-time context."""
from math import isfinite
from collections import defaultdict
from statistics import mean
from tradebot.opportunity_journal_v3 import ROUTE

def finite(x):
    return type(x) in (int,float) and isfinite(x)

def classify(context,signal):
    f=context.get("market",{}).get("frames",{}).get(signal["frame"],{})
    result={"trend":"unknown","volatility":"unknown","volume":"unknown","alignment":"unknown"}
    if f.get("status")!="ready" or f.get("closed_at")!=signal["closed_at"]:
        return result
    x=f.get("features",{})
    a,e20,e50,plus,minus=(x.get(k) for k in ("adx14","ema20","ema50","plus_di14","minus_di14"))
    if all(finite(v) for v in (a,e20,e50,plus,minus)) and 0<=a<=100 and e20>0 and e50>0 and 0<=plus<=100 and 0<=minus<=100:
        result["trend"]="range" if a<20 else "uptrend" if a>=25 and e20>e50 and plus>minus else "downtrend" if a>=25 and e20<e50 and minus>plus else "mixed"
    v=x.get("atr14_percentile100")
    if finite(v) and 0<=v<=100: result["volatility"]="low" if v<=20 else "high" if v>=80 else "normal"
    v=x.get("rvol20")
    if finite(v) and v>=0: result["volume"]="low" if v<.8 else "high" if v>=1.5 else "normal"
    if result["trend"] in ("uptrend","downtrend"):
        result["alignment"]="aligned" if (signal["direction"]=="LONG")== (result["trend"]=="uptrend") else "countertrend"
    elif result["trend"] in ("range","mixed"): result["alignment"]="nontrend"
    return result

def regime_statistics(rows):
    groups=defaultdict(list)
    for r in rows:
        for k,v in r["regime"].items():
            groups[(r["rule_id"],r["frame"],r["direction"],r["horizon_minutes"],k,v)].append(r)
    out=[]
    for (rule,frame,side,h,dimension,regime),items in sorted(groups.items()):
        observed=[r for r in items if r["status"]=="observed"]
        vals=[r["directional_return_pct"] for r in observed]
        windows=len({(r["reference_start"],r["reference_end"]) for r in observed})
        out.append(dict(rule_id=rule,frame=frame,direction=side,horizon_minutes=h,dimension=dimension,regime=regime,
            signals=len(items),observed=len(vals),distinct_windows=windows,
            mean_directional_return_pct=mean(vals) if vals else None,
            positive_direction_fraction=sum(v>0 for v in vals)/len(vals) if vals else None,
            evidence="descriptive_only" if windows>=30 else "insufficient_sample"))
    return out

def advisory(symbol,stats,*,as_of):
    # Bounded deterministic digest; never rank strategies by observed return.
    known=[r for r in stats if r["regime"]!="unknown" and r["observed"]]
    return {"symbol":symbol,"model_if_enabled":ROUTE[symbol],"as_of":as_of,"mode":"advisory_research",
        "observed_groups":len(known),"groups_with_30_windows":sum(r["distinct_windows"]>=30 for r in known),
        "examples":known[:24],"truncated":len(known)>24,"strategy_eligibility_changed":False,
        "warning":"Uncalibrated labels, correlated windows and gross price returns; not verified profitability or indicator causality."}
