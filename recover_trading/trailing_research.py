"""Offline trailing and cost-offset stop research on fixed historical windows."""
import argparse,json,math,sqlite3
from pathlib import Path
from contextlib import closing
from collections import defaultdict
from .backtest import load_bars
from .bracket_research import window,statistics,simulate as fixed
from .dynamic_bracket import evidence,FRAME

MODELS=("fixed_atr","cost_offset","trail_1atr","trail_2atr","cost_offset_and_trail")
def simulate(rows,side,atr_bps,cost,model,*,ambiguous="stop"):
    if side not in ("LONG","SHORT") or model not in MODELS or ambiguous not in ("stop","target"):
        raise ValueError("invalid research hypothesis")
    if not all(type(x) in (int,float) and math.isfinite(x) for x in (atr_bps,cost)) or not 0<atr_bps<10000/3 or not 0<=cost<10000:
        raise ValueError("invalid distances")
    if len(rows)<2:raise ValueError("incomplete price window")
    if model=="fixed_atr":
        return {**fixed(rows,side,atr_bps,3*atr_bps,cost,ambiguous=ambiguous),"adjustments":0}
    sign=1 if side=="LONG" else -1
    entry=rows[0]["open"]
    stop=-atr_bps;target=3*atr_bps;peak=0;updates=0
    def ret(price):return sign*(price/entry-1)*10000
    def done(gross,reason,amb=False):
        return {"gross_bps":gross,"net_bps":gross-cost,"exit_reason":reason,"ambiguous":amb,"adjustments":updates}
    for i,row in enumerate(rows):
        op=ret(row["open"])
        # Only the previously established stop applies to this bar.
        if op<=stop:return done(op,"stop_gap")
        if op>=target:return done(target,"target_gap")
        if i==len(rows)-1:return done(op,"time_exit")
        high=max(ret(row["high"]),ret(row["low"]))
        low=min(ret(row["high"]),ret(row["low"]))
        if low<=stop and high>=target:
            return done(stop if ambiguous=="stop" else target,ambiguous,True)
        if low<=stop:return done(stop,"stop")
        if high>=target:return done(target,"target")
        # Update from a fully completed surviving candle. Never retroactively
        # trigger the new stop against the same candle's low/high.
        peak=max(peak,high)
        proposal=stop
        if model in ("cost_offset","cost_offset_and_trail") and peak>=max(atr_bps,cost):
            proposal=max(proposal,cost)
        if model in ("trail_1atr","trail_2atr","cost_offset_and_trail"):
            distance=(2 if model=="trail_2atr" else 1)*atr_bps
            if peak>=distance:proposal=max(proposal,peak-distance)
        if proposal>stop:
            stop=proposal;updates+=1
    raise ValueError("empty window")

def analyze(database,report,*,minimum=50):
    if not report.get("complete"):raise ValueError("completed replay required")
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
        atr=ev["atr"]/ev["close"]*10000 if ev else None
        if rows is None or atr is None or not 0<atr<10000/3:
            missing+=1;continue
        key=(e["partition"],e["horizon_s"])
        for model in MODELS:
            for policy in ("stop","target"):
                groups[(*key,model,policy)].append(simulate(rows,e["side"],atr,cost,model,ambiguous=policy))
    results=[{"partition":k[0],"horizon_s":k[1],"model":k[2],"ambiguity_policy":k[3],
              "adjusted_count":sum(r["adjustments"]>0 for r in v),**statistics(v)} for k,v in sorted(groups.items())]
    lookup={(r["partition"],r["horizon_s"],r["model"],r["ambiguity_policy"]):r for r in results}
    comparisons=[]
    for h in sorted({k[1] for k in groups}):
        train=[r for r in results if r["partition"]=="development" and r["horizon_s"]==h and r["ambiguity_policy"]=="stop" and r["samples"]>=minimum]
        if not train:continue
        best=max(train,key=lambda r:(r["mean_net_bps"],r["model"]))
        comparisons.append({"horizon_s":h,"development_selected":best,
          "inspected_holdout":lookup.get(("holdout",h,best["model"],"stop")),
          "holdout_fixed_atr":lookup.get(("holdout",h,"fixed_atr","stop"))})
    return {"version":"trailing-research-v1","symbol":report["symbol"],"cost_bps":cost,"models":list(MODELS),
            "missing":missing,"results":results,"comparisons":comparisons,"execution_changed":False,
            "limitations":["Research only; original entry and time exit windows.",
              "Initial stop 1 ATR and target 3 ATR; ATR fixed at decision time.",
              "Stop adjustments from completed bars become effective on next bar only.",
              "Cost-offset stop is not guaranteed breakeven; gaps and actual costs vary.",
              "No funding, liquidation, mark-trigger or order fill simulation.",
              "Previously inspected holdout is descriptive, not fresh independent validation."]}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",required=True);p.add_argument("--report",required=True);p.add_argument("--output",required=True)
    a=p.parse_args()
    if Path(a.output).resolve() in (Path(a.database).resolve(),Path(a.report).resolve()):p.error("separate output required")
    r=analyze(a.database,json.loads(Path(a.report).read_text()))
    Path(a.output).write_text(json.dumps(r,indent=2,allow_nan=False)+"\n")
if __name__=="__main__":main()
