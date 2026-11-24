"""Persistent advisory profiles. Historical and forward samples never pooled."""
from collections import defaultdict,Counter
from statistics import mean
from pathlib import Path
from math import isfinite
import json
from tradebot.opportunity_journal_v3 import digest
from tradebot.bitcoin_strategies_v3 import RULES as BTC
from tradebot.gold_strategies_v3 import RULES as GOLD
from tradebot.advanced_backtest_v3 import COSTS

REGISTRY={"BTCUSD":BTC,"XAUTUSD":GOLD}

def forward_profiles(rows):
    groups=defaultdict(list)
    for r in rows:
        groups[(r["rule_id"],r["frame"],r["direction"],r["horizon_minutes"])].append(r)
    out=defaultdict(list)
    for (rule,frame,side,h),items in sorted(groups.items()):
        observed=sorted((r for r in items if r["status"]=="observed"),key=lambda r:(r["reference_start"],r["reference_end"],r["event_id"]))
        chosen=[]; end=0
        for r in observed:
            if r["reference_start"]>=end:
                chosen.append(r); end=r["reference_end"]
        n=len(chosen); gross=[r["directional_return_pct"] for r in chosen]
        stats={"frame":frame,"side":side,"horizon":h,"signals":len(items),"observed":len(observed),
               "nonoverlapping_samples":n,"overlap_excluded":len(observed)-n,
               "pending":sum(r["status"]=="pending" for r in items),
               "missing":sum(r["status"]=="missing_candles" for r in items),
               "sample_status":"insufficient_sample" if n<30 else "descriptive_only",
               "mean_favorable_excursion_pct":mean(r["favorable_excursion_pct"] for r in chosen) if n else None,
               "mean_adverse_excursion_pct":mean(r["adverse_excursion_pct"] for r in chosen) if n else None,
               "cost_scenarios":{str(c):{"positive_fraction":sum(x>c/100 for x in gross)/n if n else None,
                     "mean_pct":mean(gross)-c/100 if n else None} for c in COSTS}}
        buckets=defaultdict(list)
        for r in chosen:
            for d,v in r["regime"].items(): buckets[(d,v)].append(r["directional_return_pct"])
        stats["regime_profiles"]=[dict(dimension=d,value=v,samples=len(xs),mean_after_10bps_pct=mean(xs)-.1,
            positive_after_10bps=sum(x>.1 for x in xs),sample_status="insufficient_sample" if len(xs)<30 else "descriptive_only")
            for (d,v),xs in sorted(buckets.items())]
        out[rule].append(stats)
    return out

def historical(root,now):
    reports=[]
    for name in ("a","b"):
        p=Path(root)/f"m14-profile-window-{name}-v3.json"
        try:
            if p.is_symlink() or p.stat().st_size>8_000_000: continue
            r=json.loads(p.read_text())
            if r["mode"]!="fixed_rule_chronological_validation" or r["execution_authorized"] is not False or not 0<r["start"]<r["end"]<=now: continue
            if reports and r["start"]<reports[-1]["end"]: continue
            reports.append(r)
        except (OSError,ValueError,TypeError,KeyError): continue
    return reports

def build(root,rows_by_market,*,now,coverage_by_market):
    reports=historical(root,now)
    out={"mode":"strategy_performance_advisory","checked_at":now,
         "historical_windows":[{"start":r["start"],"end":r["end"],"sha256":digest(r)} for r in reports],
         "markets":{},"strategy_eligibility_changed":False,"execution_authorized":False,
         "warning":"Historical fixed scenarios and forward shadow observations are separate. Samples across groups are correlated. No actual P&L, funding, leverage or calibrated confidence."}
    for s,rules in REGISTRY.items():
        forward=forward_profiles(rows_by_market[s]); profiles=[]
        for rule in rules:
            history=[]
            for r in reports:
                m=r["markets"][s]
                history.append({"start":r["start"],"end":r["end"],
                    "coverage":[x for x in m["coverage"] if x["rule_id"]==rule.id],
                    "scenarios":[x for x in m["groups"] if x["rule_id"]==rule.id]})
            profiles.append({"rule_id":rule.id,"name":rule.name,"frames":list(rule.frames),
                "historical":history,"forward_shadow":forward.get(rule.id,[]),
                "actual_trade_outcomes":None})
        out["markets"][s]={"profiles":profiles,"forward_event_coverage":coverage_by_market[s]}
    return out

def advisory(report,symbol,signals,*,as_of):
    """Compact exact-rule evidence for a future offline decision preview."""
    if report.get("mode")!="strategy_performance_advisory" or report.get("execution_authorized") is not False or not 0<=as_of-report["checked_at"]<=660:
        return {"status":"unavailable","strategy_eligibility_changed":False}
    p={x["rule_id"]:x for x in report["markets"][symbol]["profiles"]}
    result=[]
    for rule,frame,side in sorted({(x["id"],x["frame"],x["direction"]) for x in signals})[:12]:
        if rule not in p or frame not in p[rule]["frames"]: continue
        x=p[rule]; history=[]
        for w in x["historical"]:
            rows=[g for g in w["scenarios"] if g["frame"]==frame and g["side"]==side and g["horizon"]==60 and g["scenario"]=="fixed"]
            history.append({"start":w["start"],"end":w["end"],"scenarios":[{k:g[k] for k in ("samples","sample_status","cost_scenarios")} for g in rows]})
        forward=[{k:g[k] for k in ("nonoverlapping_samples","sample_status","cost_scenarios")} for g in x["forward_shadow"] if g["frame"]==frame and g["side"]==side and g["horizon"]==60]
        result.append({"rule_id":rule,"frame":frame,"side":side,"historical":history,"forward_shadow":forward})
    return {"status":"research_advisory","checked_at":report["checked_at"],"profiles":result,
            "strategy_eligibility_changed":False,"execution_authorized":False}
