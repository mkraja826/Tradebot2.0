"""Offline bracket sensitivity on existing reference replay windows. No orders."""
import argparse
import json
import math
from collections import Counter,defaultdict
from pathlib import Path
from statistics import mean
from .backtest import STEP,load_bars
from tradebot.market_data_v3 import normalize

STOPS=(20,40,80)
TARGETS=(30,60,120)
GRID=tuple((s,t) for s in STOPS for t in TARGETS)

def window(bars,e):
    a,b=e["entry_at"],e["exit_at"]
    if type(a) is not int or type(b) is not int or a%STEP or b%STEP or b<=a:
        raise ValueError("invalid window")
    try:
        rows=normalize([bars[t] for t in range(a,b+STEP,STEP)],"5m",as_of=b+STEP,count=(b-a)//STEP+1)
    except (KeyError,ValueError):
        return None
    if not math.isclose(rows[0]["open"],e["entry"],rel_tol=1e-10) or not math.isclose(rows[-1]["open"],e["exit"],rel_tol=1e-10):
        return None
    return rows

def simulate(rows,side,stop_bps,target_bps,cost_bps,*,ambiguous="stop"):
    if side not in ("LONG","SHORT") or ambiguous not in ("stop","target"):
        raise ValueError("invalid scenario")
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (stop_bps,target_bps,cost_bps)) or not 0<stop_bps<10000 or not 0<target_bps<10000 or cost_bps<0:
        raise ValueError("invalid distances or cost")
    sign=1 if side=="LONG" else -1
    entry=rows[0]["open"]
    stop=entry*(1-sign*stop_bps/10000)
    target=entry*(1+sign*target_bps/10000)
    def done(price,reason,amb=False):
        gross=sign*(price/entry-1)*10000
        return {"gross_bps":gross,"net_bps":gross-cost_bps,"exit_reason":reason,"ambiguous":amb}
    for i,row in enumerate(rows):
        op=row["open"]
        # Stop gap: worse opening fill assumed. Target gap: no price improvement.
        if sign*(op-stop)<=0:return done(op,"stop_gap")
        if sign*(op-target)>=0:return done(target,"target_gap")
        if i==len(rows)-1:return done(op,"time_exit")
        hit_stop=row["low"]<=stop if sign==1 else row["high"]>=stop
        hit_target=row["high"]>=target if sign==1 else row["low"]<=target
        if hit_stop and hit_target:
            return done(stop if ambiguous=="stop" else target,"stop" if ambiguous=="stop" else "target",True)
        if hit_stop:return done(stop,"stop")
        if hit_target:return done(target,"target")
    raise ValueError("empty window")

def statistics(rows):
    n=len(rows)
    return {"samples":n,"mean_net_bps":mean(r["net_bps"] for r in rows) if n else None,
            "win_rate":sum(r["net_bps"]>0 for r in rows)/n if n else None,
            "ambiguous_count":sum(r["ambiguous"] for r in rows),
            "exit_counts":dict(Counter(r["exit_reason"] for r in rows))}

def analyze(database,report,*,minimum=50):
    if not report.get("complete"):raise ValueError("completed replay required")
    bars=load_bars(database,report["symbol"],report["start"],report["end"])
    cost=report["cost_bps_round_trip"]
    groups=defaultdict(list); baseline=defaultdict(list); missing=0
    # Existing nonoverlapping windows are reused, even when a bracket exits early.
    # No additional entries or changes to the historical signal engine.
    for e in report["events"]:
        if e["rule_id"]!="ensemble_v2":continue
        rows=window(bars,e)
        if rows is None:missing+=1;continue
        key=(e["partition"],e["horizon_s"])
        baseline[key].append({"net_bps":e["net_bps"],"ambiguous":False,"exit_reason":"time_exit"})
        for s,t in GRID:
            for policy in ("stop","target"):
                groups[(*key,s,t,policy)].append(simulate(rows,e["side"],s,t,cost,ambiguous=policy))
    results=[{"partition":k[0],"horizon_s":k[1],"stop_bps":k[2],"target_bps":k[3],"ambiguity_policy":k[4],**statistics(v)} for k,v in sorted(groups.items())]
    lookup={(r["partition"],r["horizon_s"],r["stop_bps"],r["target_bps"],r["ambiguity_policy"]):r for r in results}
    comparisons=[]
    for h in sorted({k[1] for k in baseline}):
        training=[r for r in results if r["partition"]=="development" and r["horizon_s"]==h and r["ambiguity_policy"]=="stop" and r["samples"]>=minimum]
        if not training:continue
        best=max(training,key=lambda r:(r["mean_net_bps"],-r["stop_bps"],-r["target_bps"]))
        s,t=best["stop_bps"],best["target_bps"]
        comparisons.append({"horizon_s":h,"development_selected":best,
            "inspected_holdout_stop_first":lookup.get(("holdout",h,s,t,"stop")),
            "inspected_holdout_target_first":lookup.get(("holdout",h,s,t,"target")),
            "development_baseline":statistics(baseline[("development",h)]),
            "holdout_baseline":statistics(baseline[("holdout",h)])})
    return {"version":"bracket-research-v1","symbol":report["symbol"],"cost_bps":cost,
            "missing":missing,"grid":[list(x) for x in GRID],"results":results,"comparisons":comparisons,
            "execution_changed":False,"limitations":["Fixed price distances are experimental grid hypotheses, not recommendations.",
              "Only original Engine 2.0 entry windows are reused; no entry optimization yet.",
              "Five-minute OHLC cannot establish intrabar ordering or executable prices.",
              "Stop-first and target-first are assumptions, not guaranteed bounds on actual fills.",
              "Stop gaps use opening price; target gaps use target price; no funding or liquidation simulation.",
              "Development selection is exploratory; previously inspected holdout is not fresh validation."]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",required=True);p.add_argument("--report",required=True);p.add_argument("--output",required=True)
    a=p.parse_args()
    if Path(a.output).resolve() in (Path(a.database).resolve(),Path(a.report).resolve()):p.error("separate output required")
    r=analyze(a.database,json.loads(Path(a.report).read_text()))
    Path(a.output).write_text(json.dumps(r,indent=2,allow_nan=False)+"\n")
if __name__=="__main__":main()
