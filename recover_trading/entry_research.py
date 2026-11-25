"""Offline entry timing on fixed replay windows; no AI or exchange actions."""
import argparse,json,math
from collections import defaultdict
from statistics import mean,median
from pathlib import Path
from .backtest import load_bars,STEP
from .bracket_research import window

MODELS=("original","delay_5m","delay_10m","confirm_direction","pullback_reclaim")

def entry_index(rows,side,model):
    """Use only completed candles before the candidate entry open."""
    if side not in ("LONG","SHORT") or model not in MODELS:
        raise ValueError("invalid entry hypothesis")
    sign=1 if side=="LONG" else -1
    # Final candle is reserved for the fixed exit; no entry at that open.
    if model=="original":return 0 if len(rows)>1 else None
    if model in ("delay_5m","delay_10m"):
        i=1 if model=="delay_5m" else 2
        return i if i<len(rows)-1 else None
    # Observe at most two completed 5m candles after the original entry.
    anchor=rows[0]["open"]
    pulled=False
    for i in range(1,min(3,len(rows)-1)):
        bar=rows[i-1]
        if model=="confirm_direction":
            if sign*(bar["close"]-bar["open"])>0 and sign*(bar["close"]-anchor)>0:
                return i
        else:
            # Require a completed adverse close, then a later completed
            # candle reclaiming that adverse candle's open.
            if pulled and sign*(bar["close"]-rows[i-2]["open"])>=0:
                return i
            if sign*(bar["close"]-anchor)<0:pulled=True
    return None

def simulate(rows,side,model,cost):
    if not math.isfinite(cost) or cost<0:raise ValueError("invalid cost")
    idx=entry_index(rows,side,model)
    if idx is None:return {"entered":False,"net_bps":0.0,"gross_bps":0.0,"delay_s":None}
    sign=1 if side=="LONG" else -1
    gross=sign*(rows[-1]["open"]/rows[idx]["open"]-1)*10000
    return {"entered":True,"net_bps":gross-cost,"gross_bps":gross,"delay_s":idx*STEP}

def summarize(rows):
    n=len(rows); filled=[r for r in rows if r["entered"]]
    return {"opportunities":n,"entries":len(filled),"untriggered":n-len(filled),
        "entry_fraction":len(filled)/n if n else None,
        "mean_net_bps_per_opportunity":mean(r["net_bps"] for r in rows) if n else None,
        "mean_net_bps_per_entry":mean(r["net_bps"] for r in filled) if filled else None,
        "win_rate_per_entry":sum(r["net_bps"]>0 for r in filled)/len(filled) if filled else None,
        "median_extra_delay_s":median(r["delay_s"] for r in filled) if filled else None}

def analyze(database,report,*,minimum=50):
    if not report.get("complete"):raise ValueError("completed replay required")
    bars=load_bars(database,report["symbol"],report["start"],report["end"])
    cost=report["cost_bps_round_trip"]
    groups=defaultdict(list);missing=0
    for e in report["events"]:
        if e["rule_id"]!="ensemble_v2":continue
        rows=window(bars,e)
        if rows is None:
            missing+=1;continue
        for m in MODELS:
            groups[(e["partition"],e["horizon_s"],m)].append(simulate(rows,e["side"],m,cost))
    results=[{"partition":k[0],"horizon_s":k[1],"model":k[2],**summarize(v)} for k,v in sorted(groups.items())]
    lookup={(r["partition"],r["horizon_s"],r["model"]):r for r in results}
    comparisons=[]
    for h in sorted({k[1] for k in groups}):
        train=[r for r in results if r["partition"]=="development" and r["horizon_s"]==h and r["entries"]>=minimum]
        if not train:continue
        best=max(train,key=lambda r:(r["mean_net_bps_per_opportunity"],r["entries"],r["model"]))
        comparisons.append({"horizon_s":h,"development_selected":best,
          "inspected_holdout":lookup.get(("holdout",h,best["model"])),
          "holdout_baseline":lookup.get(("holdout",h,"original"))})
    return {"version":"entry-timing-research-v1","symbol":report["symbol"],"cost_bps":cost,
        "models":list(MODELS),"missing":missing,"results":results,"comparisons":comparisons,
        "execution_changed":False,"limitations":["Original replay starts five minutes after the decision, not an immediate real fill.",
          "Delay and confirmation entries use the next open after completed candles; fixed original exit shortens the holding time.",
          "Untriggered opportunities contribute zero to per-opportunity return, and no cost.",
          "No new opportunities are introduced after a missed or earlier entry; original nonoverlapping windows retained.",
          "Results are unleveraged price simulations without funding or actual fill modeling.",
          "Development selection is exploratory; previously inspected holdout is not fresh validation."]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",required=True);p.add_argument("--report",required=True);p.add_argument("--output",required=True)
    a=p.parse_args()
    if Path(a.output).resolve() in (Path(a.database).resolve(),Path(a.report).resolve()):p.error("separate output required")
    r=analyze(a.database,json.loads(Path(a.report).read_text()))
    Path(a.output).write_text(json.dumps(r,indent=2,allow_nan=False)+"\n")
if __name__=="__main__":main()
