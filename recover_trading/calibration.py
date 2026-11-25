"""Offline exploratory training scores. Never modifies execution weights."""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

DAY=86400
def candidate_report(report,*,minimum=50,minimum_weeks=8,draws=2000,seed=42):
    if not report.get("complete"):
        raise ValueError("complete replay required")
    if minimum<1 or minimum_weeks<2 or draws<100:
        raise ValueError("invalid calibration settings")
    start,split=report["start"],report["split"]
    groups=defaultdict(lambda:defaultdict(list))
    for e in report["events"]:
        if e["partition"]!="development" or e["rule_id"].startswith("ensemble_"):
            continue
        if not start<=e["decision_at"]<split or e["exit_at"]+300>split:
            raise ValueError("development event crosses boundary")
        week=(e["decision_at"]-start)//(7*DAY)
        # Drop incomplete trailing week, rather than treat as a full cluster.
        if start+(week+1)*7*DAY>split:
            continue
        groups[(e["rule_id"],e["horizon_s"])][week].append(e["net_bps"])
    rows=[]
    for (ident,horizon),weeks in sorted(groups.items()):
        totals=[(sum(v),len(v)) for _,v in sorted(weeks.items())]
        n=sum(b for a,b in totals); mean=sum(a for a,b in totals)/n
        row={"rule_id":ident,"horizon_s":horizon,"samples":n,
             "active_weeks":len(totals),"mean_net_bps":mean,
             "weekly_positive_fraction":sum(a>0 for a,b in totals)/len(totals),
             "lower_bps":None,"upper_bps":None,"research_status":"insufficient_samples"}
        if n>=minimum and len(totals)>=minimum_weeks:
            rng=random.Random(seed)
            means=[]
            for _ in range(draws):
                sample=rng.choices(totals,k=len(totals))
                means.append(sum(a for a,b in sample)/sum(b for a,b in sample))
            means.sort()
            lo,hi=means[int(.025*draws)],means[min(draws-1,int(.975*draws))]
            row.update(lower_bps=lo,upper_bps=hi,
                       research_status="positive_training_candidate" if lo>0 else "no_positive_training_evidence")
        rows.append(row)
    return {"version":"weekly-cluster-training-v1","symbol":report["symbol"],
            "development_start":start,"development_end_exclusive":split,
            "minimum_samples":minimum,"minimum_active_weeks":minimum_weeks,"draws":draws,
            "cost_bps_round_trip":report["cost_bps_round_trip"],"rows":rows,
            "positive_training_candidates":sum(x["research_status"]=="positive_training_candidate" for x in rows),
            "execution_weights_changed":False,
            "limitations":["exploratory weekly cluster bootstrap, conditional on active weeks",
                "small number of weeks, serial dependence and multiple comparisons limit inference",
                "holdout excluded from training; already inspected holdout is not fresh validation",
                "no weight approval; prospective independent validation required"]}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("report")
    p.add_argument("--output",required=True)
    a=p.parse_args()
    if Path(a.report).resolve()==Path(a.output).resolve():
        p.error("output must differ from replay input")
    result=candidate_report(json.loads(Path(a.report).read_text()))
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"symbol":result["symbol"],"rows":len(result["rows"]),
                      "positive_training_candidates":result["positive_training_candidates"]}))
if __name__=="__main__":
    main()
