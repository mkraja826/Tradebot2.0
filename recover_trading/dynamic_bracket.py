"""Offline point-in-time ATR and market-structure bracket research."""
import argparse,json,math,sqlite3
from pathlib import Path
from contextlib import closing
from collections import defaultdict
from statistics import median
from tradebot.market_data_v3 import normalize
from tradebot.indicator_math_v3 import volatility
from .backtest import load_bars
from .bracket_research import window,simulate,statistics

FRAME=900
MODELS=("atr_1x_1.5x","atr_1x_2x","atr_2x_3x","structure_atr","structure_buffered")

def evidence(bars,at):
    """Exact completed 15m window; excludes candle beginning at decision."""
    end=at//FRAME*FRAME
    try:
        rows=normalize([bars[t] for t in range(end-250*FRAME,end,FRAME)],"15m",as_of=at,count=250)
    except (KeyError,ValueError):
        return None
    h,l,c=([r[k] for r in rows] for k in ("high","low","close"))
    atr=volatility(h,l,c)["atr14"]
    if atr is None or not math.isfinite(atr) or atr<=0:
        return None
    return {"atr":atr,"close":c[-1],"prior_high":max(h[-21:-1]),"prior_low":min(l[-21:-1]),"closed_at":end}

def distances(e,side,model):
    """All distances fixed at decision; expressed relative to decision close."""
    a,p=e["atr"],e["close"]
    if side not in ("LONG","SHORT") or model not in MODELS:raise ValueError("invalid hypothesis")
    if model=="atr_1x_1.5x":s,t=a,1.5*a
    elif model=="atr_1x_2x":s,t=a,2*a
    elif model=="atr_2x_3x":s,t=2*a,3*a
    else:
        # Historical structural distances are measured at signal time, then
        # applied relative to delayed entry; not fixed absolute limit prices.
        opposite=p-e["prior_low"] if side=="LONG" else e["prior_high"]-p
        ahead=e["prior_high"]-p if side=="LONG" else p-e["prior_low"]
        s=max(a,opposite)
        t=max(1.5*a,ahead)
        if model=="structure_buffered":
            s+=.5*a;t+=.5*a
    result=(s/p*10000,t/p*10000)
    return result if all(math.isfinite(x) and 0<x<10000 for x in result) else None

def analyze(database,report,*,minimum=50):
    if not report.get("complete"):raise ValueError("completed replay required")
    bars=load_bars(database,report["symbol"],report["start"],report["end"])
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        source={t:json.loads(p) for t,p in db.execute(
          "SELECT stamp,payload FROM samples WHERE symbol=? AND series='candle:15m' AND stamp>=? AND stamp<?",
          (report["symbol"],report["start"]-250*FRAME,report["end"]))}
    cache={}; groups=defaultdict(list); baseline=defaultdict(list); sizes=defaultdict(list);missing=0
    cost=report["cost_bps_round_trip"]
    for event in report["events"]:
        if event["rule_id"]!="ensemble_v2":continue
        at=event["decision_at"]
        if at not in cache:cache[at]=evidence(source,at)
        ev=cache[at]; rows=window(bars,event)
        if ev is None or rows is None:
            missing+=1;continue
        ds={m:distances(ev,event["side"],m) for m in MODELS}
        # All alternatives and baseline share identical valid entry windows.
        if any(v is None for v in ds.values()):
            missing+=1;continue
        key=(event["partition"],event["horizon_s"])
        baseline[key].append({"net_bps":event["net_bps"],"ambiguous":False,"exit_reason":"time_exit"})
        for model,(s,t) in ds.items():
            sizes[(*key,model)].append((s,t))
            for policy in ("stop","target"):
                groups[(*key,model,policy)].append(simulate(rows,event["side"],s,t,cost,ambiguous=policy))
    results=[]
    for k,v in sorted(groups.items()):
        z=sizes[k[:3]]
        results.append({"partition":k[0],"horizon_s":k[1],"model":k[2],"ambiguity_policy":k[3],
            "median_stop_bps":median(x[0] for x in z),"median_target_bps":median(x[1] for x in z),**statistics(v)})
    lookup={(r["partition"],r["horizon_s"],r["model"],r["ambiguity_policy"]):r for r in results}
    comparisons=[]
    for h in sorted({k[1] for k in baseline}):
        train=[r for r in results if r["partition"]=="development" and r["horizon_s"]==h and r["ambiguity_policy"]=="stop" and r["samples"]>=minimum]
        if not train:continue
        selected=max(train,key=lambda x:(x["mean_net_bps"],x["model"]))
        comparisons.append({"horizon_s":h,"development_selected":selected,
            "inspected_holdout_stop_first":lookup.get(("holdout",h,selected["model"],"stop")),
            "inspected_holdout_target_first":lookup.get(("holdout",h,selected["model"],"target")),
            "holdout_baseline":statistics(baseline[("holdout",h)])})
    return {"version":"dynamic-bracket-research-v1","symbol":report["symbol"],"cost_bps":cost,
            "models":list(MODELS),"missing":missing,"results":results,"comparisons":comparisons,
            "execution_changed":False,"limitations":["Experimental offline hypotheses only.",
              "15m ATR and prior 20-bar structure fixed at decision; no future candles used for distances.",
              "Structural distances translated to delayed entry, not absolute support/resistance orders.",
              "Same original entry windows; no additional entries, trailing exits, funding or liquidation.",
              "Five-minute OHLC does not establish actual fill prices or intrabar order.",
              "Previously inspected holdout is descriptive, not fresh independent validation."]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",required=True);p.add_argument("--report",required=True);p.add_argument("--output",required=True)
    a=p.parse_args()
    if Path(a.output).resolve() in (Path(a.database).resolve(),Path(a.report).resolve()):p.error("separate output required")
    r=analyze(a.database,json.loads(Path(a.report).read_text()))
    Path(a.output).write_text(json.dumps(r,indent=2,allow_nan=False)+"\n")
if __name__=="__main__":main()
