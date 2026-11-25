"""Offline cost-sensitivity analysis of a completed reference replay."""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

COSTS=(0,5,10,15,20,30)
def sensitivity(report,*,costs=COSTS,minimum=20):
    if not report.get("complete"):
        raise ValueError("completed replay required")
    if not costs or any(type(c) not in (float,int) or not math.isfinite(c) or c<0 for c in costs):
        raise ValueError("invalid costs")
    groups=defaultdict(list)
    for e in report["events"]:
        p=e["partition"]
        if p not in ("development","holdout"):
            raise ValueError("invalid partition")
        g=e["gross_bps"]
        if not math.isfinite(g):
            raise ValueError("nonfinite gross return")
        groups[(p,e["rule_id"],e["horizon_s"])].append(g)
    rows=[]
    for (p,ident,h),v in sorted(groups.items()):
        avg=mean(v)
        rows.append({"partition":p,"rule_id":ident,"horizon_s":h,"samples":len(v),
                     "eligible":len(v)>=minimum,"mean_gross_bps":avg,"median_gross_bps":median(v),
                     "break_even_round_trip_bps":max(0,avg) if avg>0 else None,
                     "scenarios":[{"cost_bps":c,"mean_net_bps":avg-c,
                                   "win_rate":sum(x>c for x in v)/len(v)} for c in costs]})
    return {"symbol":report["symbol"],"version":"cost-sensitivity-v1","minimum_samples":minimum,
            "cost_scenarios_bps":list(costs),"rows":rows,"execution_weights_changed":False,
            "limitations":["Hypothetical all-in cost scenarios; actual fill fees, spread, slippage and funding vary.",
                           "Fixed-horizon returns are not leveraged portfolio P&L.",
                           "Holdout already inspected; results are descriptive, not fresh validation."]}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("report");p.add_argument("--output",required=True)
    a=p.parse_args()
    if Path(a.report).resolve()==Path(a.output).resolve():
        p.error("output must differ from input")
    result=sensitivity(json.loads(Path(a.report).read_text()))
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
if __name__=="__main__":
    main()
