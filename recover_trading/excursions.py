"""Historical MFE/MAE diagnostics, based on observed OHLC ranges, not fill simulation."""
import argparse,json,math
from pathlib import Path
from collections import defaultdict
from statistics import median
from .backtest import load_bars,STEP
from tradebot.market_data_v3 import normalize

def excursion(bars,event):
    a,b=event["entry_at"],event["exit_at"]
    if type(a) is not int or type(b) is not int or a%STEP or b%STEP or b<=a:
        raise ValueError("invalid excursion window")
    # Include exit OPEN only. Never use the exit candle's later high/low.
    try:
        rows=normalize([bars[t] for t in range(a,b+STEP,STEP)],"5m",as_of=b+STEP,count=(b-a)//STEP+1)
    except (KeyError,ValueError):return None
    entry=rows[0]["open"]; exit=rows[-1]["open"]
    if not math.isclose(entry,event["entry"],rel_tol=1e-10) or not math.isclose(exit,event["exit"],rel_tol=1e-10):
        return None
    hi=max(exit,max(x["high"] for x in rows[:-1]))
    lo=min(exit,min(x["low"] for x in rows[:-1]))
    if event["side"]=="LONG":fav,adv=hi/entry-1,1-lo/entry
    elif event["side"]=="SHORT":fav,adv=1-lo/entry,hi/entry-1
    else:raise ValueError("invalid direction")
    return {"mfe_bps":max(0,fav*10000),"mae_bps":max(0,adv*10000)}

def report_excursions(database,report):
    if not report.get("complete"):raise ValueError("completed replay required")
    bars=load_bars(database,report["symbol"],report["start"],report["end"])
    groups=defaultdict(list); missing=0
    for e in report["events"]:
        r=excursion(bars,e)
        if r is None:missing+=1;continue
        groups[(e["partition"],e["rule_id"],e["horizon_s"],e["regime"])].append(r)
        groups[(e["partition"],e["rule_id"],e["horizon_s"],"all")].append(r)
    rows=[]
    for k,v in sorted(groups.items()):
        rows.append({"partition":k[0],"rule_id":k[1],"horizon_s":k[2],"regime":k[3],
                     "samples":len(v),"median_mfe_bps":median(x["mfe_bps"] for x in v),
                     "median_mae_bps":median(x["mae_bps"] for x in v),
                     "mfe_exceeds_assumed_cost_fraction":sum(x["mfe_bps"]>report["cost_bps_round_trip"] for x in v)/len(v)})
    return {"version":"excursions-v1","symbol":report["symbol"],"missing":missing,
            "events":len(report["events"]),"rows":rows,"cost_bps_round_trip":report["cost_bps_round_trip"],
            "limitations":["OHLC extrema do not reveal intrabar ordering or executable fills",
                           "MFE is not attainable profit or a prediction",
                           "Inspected holdout is descriptive, not independent validation"]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",required=True);p.add_argument("--report",required=True);p.add_argument("--output",required=True)
    a=p.parse_args()
    if Path(a.output).resolve() in (Path(a.database).resolve(),Path(a.report).resolve()):p.error("separate output required")
    r=report_excursions(a.database,json.loads(Path(a.report).read_text()))
    Path(a.output).write_text(json.dumps(r,indent=2,allow_nan=False)+"\n")
if __name__=="__main__":main()
