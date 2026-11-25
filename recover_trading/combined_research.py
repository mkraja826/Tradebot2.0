"""Offline paired entry/exit experiments over the original reference replay."""
import argparse,json,sqlite3,math
from pathlib import Path
from contextlib import closing
from collections import defaultdict,Counter
from .backtest import load_bars,STEP
from .bracket_research import window,simulate as bracket
from .entry_research import MODELS as ENTRIES,entry_index,summarize
from .dynamic_bracket import FRAME,evidence,distances,MODELS as DYNAMIC
from .trailing_research import MODELS as TRAILING,simulate as trailing

EXITS=("time_exit",)+DYNAMIC+TRAILING
def simulate(rows,side,ev,entry_model,exit_model,cost,*,ambiguity="stop"):
    if exit_model not in EXITS or ambiguity not in ("stop","target"):
        raise ValueError("unknown exit hypothesis")
    if not math.isfinite(cost) or cost<0:raise ValueError("invalid cost")
    idx=entry_index(rows,side,entry_model)
    if idx is None:
        return {"entered":False,"net_bps":0.0,"gross_bps":0.0,"delay_s":None,
                "exit_reason":"untriggered","ambiguous":False}
    path=rows[idx:]
    # Use the decision-time evidence, never recalculate it from future bars.
    if exit_model=="time_exit":
        sign=1 if side=="LONG" else -1
        gross=sign*(path[-1]["open"]/path[0]["open"]-1)*10000
        result={"gross_bps":gross,"net_bps":gross-cost,"exit_reason":"time_exit","ambiguous":False}
    elif exit_model in DYNAMIC:
        s,t=distances(ev,side,exit_model)
        result=bracket(path,side,s,t,cost,ambiguous=ambiguity)
    else:
        atr=ev["atr"]/ev["close"]*10000
        result=trailing(path,side,atr,cost,exit_model,ambiguous=ambiguity)
    return {**result,"entered":True,"delay_s":idx*STEP}

def metrics(rows):
    return {**summarize(rows),"exit_counts":dict(Counter(r["exit_reason"] for r in rows)),
            "ambiguous_count":sum(r["ambiguous"] for r in rows)}

def analyze(database,report,*,minimum=50):
    if not report.get("complete"):raise ValueError("completed replay required")
    if type(minimum) is not int or minimum<1:raise ValueError("invalid research sample minimum")
    bars=load_bars(database,report["symbol"],report["start"],report["end"])
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        source={t:json.loads(p) for t,p in db.execute(
          "SELECT stamp,payload FROM samples WHERE symbol=? AND series='candle:15m' AND stamp>=? AND stamp<?",
          (report["symbol"],report["start"]-250*FRAME,report["end"]))}
    cache={};groups=defaultdict(list);missing=0
    cost=report["cost_bps_round_trip"]
    for e in report["events"]:
        if e["rule_id"]!="ensemble_v2":continue
        at=e["decision_at"]
        if at not in cache:cache[at]=evidence(source,at)
        ev=cache[at];rows=window(bars,e)
        if ev is None or rows is None or not 0<ev["atr"]/ev["close"]*10000<10000/3 or any(distances(ev,e["side"],m) is None for m in DYNAMIC):
            missing+=1;continue
        for en in ENTRIES:
            for ex in EXITS:
                for policy in ("stop","target"):
                    groups[(e["partition"],e["horizon_s"],en,ex,policy)].append(
                        simulate(rows,e["side"],ev,en,ex,cost,ambiguity=policy))
    results=[{"partition":k[0],"horizon_s":k[1],"entry_model":k[2],"exit_model":k[3],
              "ambiguity_policy":k[4],**metrics(v)} for k,v in sorted(groups.items())]
    lookup={(r["partition"],r["horizon_s"],r["entry_model"],r["exit_model"],r["ambiguity_policy"]):r for r in results}
    comparisons=[]
    for h in sorted({k[1] for k in groups}):
        train=[r for r in results if r["partition"]=="development" and r["horizon_s"]==h and r["ambiguity_policy"]=="stop" and r["entries"]>=minimum]
        if not train:continue
        # Report two objectives separately; participation can reduce loss per
        # opportunity even when the entered-trade expectancy deteriorates.
        for objective in ("mean_net_bps_per_entry","mean_net_bps_per_opportunity"):
            best=max(train,key=lambda r:(r[objective],r["entries"],r["entry_model"],r["exit_model"]))
            en,ex=best["entry_model"],best["exit_model"]
            comparisons.append({"horizon_s":h,"objective":objective,"development_selected":best,
                "inspected_holdout_stop_first":lookup.get(("holdout",h,en,ex,"stop")),
                "inspected_holdout_target_first":lookup.get(("holdout",h,en,ex,"target")),
                "holdout_baseline":lookup.get(("holdout",h,"original","time_exit","stop"))})
    return {"version":"combined-entry-exit-v1","symbol":report["symbol"],"cost_bps":cost,
            "entry_models":list(ENTRIES),"exit_models":list(EXITS),"missing":missing,
            "results":results,"comparisons":comparisons,"execution_changed":False,
            "limitations":["Exploratory hypotheses using the same already-inspected reference history.",
                "Original decision and fixed exit windows retained; delayed entry shortens holding time.",
                "Untriggered entries count as zero per opportunity, not zero per entered trade.",
                "ATR and structure fixed at original decision; trailing adjustments use completed bars.",
                "Intrabar ambiguity assumptions do not establish executable prices.",
                "No funding, leverage, liquidation, actual fill or portfolio simulation.",
                "Minimum sample count is research-only, not a trade gate. No independent validation."]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",required=True);p.add_argument("--report",required=True);p.add_argument("--output",required=True)
    a=p.parse_args()
    if Path(a.output).resolve() in (Path(a.database).resolve(),Path(a.report).resolve()):p.error("separate output required")
    result=analyze(a.database,json.loads(Path(a.report).read_text()))
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
if __name__=="__main__":main()
