"""Chronological, read-only Gold V2 learning report; never changes strategy."""
import argparse
import json
import sqlite3
from collections import defaultdict, Counter
from math import isfinite
from pathlib import Path
from statistics import mean, median

VERSION="gold-v2-learning.1"
POLICIES=("fixed","hybrid_exit","hybrid_scaling")
COSTS=("15","30")
MIN_TRAIN=30
MIN_EVAL=20
COHORT="gold-v2-validation.5"

def finite(x):
    return type(x) in (float,int) and isfinite(x)

def metrics(rows,policy,cost):
    pairs=[(r["values"][cost]["fixed"],r["values"][cost][policy]) for r in rows]
    if not pairs:return {"samples":0}
    delta=[y-x for x,y in pairs]
    values=[y for _,y in pairs]
    # Additive normalized-notional curve, not account equity or leveraged drawdown.
    total=peak=drawdown=0.0
    for x in values:
        total+=x;peak=max(peak,total);drawdown=max(drawdown,peak-total)
    return {"samples":len(pairs),"mean_net_bps":mean(values),
            "mean_fixed_net_bps":mean(x for x,_ in pairs),
            "mean_paired_difference_bps":mean(delta),"median_paired_difference_bps":median(delta),
            "positive_rate":sum(x>0 for x in values)/len(values),
            "worst_net_bps":min(values),"additive_drawdown_bps":drawdown}

def extract(row):
    report=json.loads(row["evidence"])
    result=json.loads(row["outcome_json"])
    if report.get("symbol")!="XAUTUSD" or result.get("status")!="evaluated":
        return [],"unusable_window"
    scores={(c["family"],c["direction"]):c for c in report.get("intelligence",{}).get("candidates",[])}
    seen=set();samples=[]
    for c in result.get("candidates",[]):
        family,side=c["family"],c["direction"]
        if side not in ("LONG","SHORT") or (family,side) in seen:
            raise ValueError("duplicate_or_invalid_candidate")
        seen.add((family,side))
        values={};version=None
        for cost in COSTS:
            packet=c.get("combined",{}).get(cost,{})
            v=packet.get("version")
            if not v or (version is not None and version!=v):break
            version=v
            out=packet.get("results",{})
            m={}
            for p in POLICIES:
                item=out.get(p,{})
                x=item.get("net_bps_initial_notional")
                if item.get("status")=="observed" and finite(x):m[p]=x
            if len(m)!=len(POLICIES):break
            values[cost]=m
        s=scores.get((family,side),{})
        key=(report.get("version","unknown"),report.get("intelligence",{}).get("version","unknown"),
             version or "unknown",family,side,report.get("regime","unknown"))
        samples.append({"group":key,"values":values if len(values)==len(COSTS) else None,
                        "support_index":s.get("support_index"),"observed_groups":s.get("observed_groups"),
                        "signal_boundary":row["signal_boundary"]})
    return samples,None

def analyze(rows,*,cutoff,as_of,min_train=MIN_TRAIN,min_eval=MIN_EVAL):
    if (type(cutoff) is not int or type(as_of) is not int or cutoff>=as_of
        or type(min_train) is not int or type(min_eval) is not int or min(min_train,min_eval)<1):
        raise ValueError("invalid_study_bounds")
    groups=defaultdict(lambda:{"train":[],"evaluation":[],"excluded_train":0,"excluded_evaluation":0})
    exclusions=Counter();seen=set()
    for row in sorted(rows,key=lambda r:r["signal_boundary"]):
        if row["policy_version"]!=COHORT:
            exclusions["different_policy_cohort"]+=1;continue
        t=row["signal_boundary"];resolved=row["resolved_at"];end=row["end_boundary"]
        if t in seen:raise ValueError("duplicate_window")
        seen.add(t)
        if (row["status"]!="resolved" or not all(finite(x) for x in (t,end,resolved))
            or not t<end<=resolved<=as_of):
            exclusions["not_resolved_at_as_of"]+=1;continue
        if t<cutoff and resolved<cutoff:phase="train"
        elif t>=cutoff:phase="evaluation"
        else:
            exclusions["crosses_training_cutoff"]+=1;continue
        samples,reason=extract(row)
        if reason:exclusions[reason]+=1;continue
        for sample in samples:
            group=groups[sample["group"]]
            if sample["values"] is None:group["excluded_"+phase]+=1
            else:group[phase].append(sample)
    proposals=[]
    for key,g in sorted(groups.items()):
        train=g["train"];ev=g["evaluation"]
        n=len(train);m=len(ev)
        selected="fixed";status="insufficient_training"
        train_stats={p:{c:metrics(train,p,c) for c in COSTS} for p in POLICIES}
        if n>=min_train:
            # Select using training only. Require improvement at both cost levels.
            eligible=[p for p in POLICIES if p!="fixed" and
                      all(train_stats[p][c]["mean_paired_difference_bps"]>0
                          and train_stats[p][c]["mean_net_bps"]>0 for c in COSTS)]
            if eligible:
                selected=max(eligible,key=lambda p:(train_stats[p]["15"]["mean_paired_difference_bps"],p))
                status="awaiting_evaluation"
            else:status="no_training_improvement"
        evaluation={c:metrics(ev,selected,c) for c in COSTS}
        if selected!="fixed" and m>=min_eval:
            status=("positive_holdout_observation" if all(
                evaluation[c]["mean_paired_difference_bps"]>0 and evaluation[c]["mean_net_bps"]>0
                for c in COSTS) else "holdout_not_confirmed")
        engine,scoring,combined,family,side,regime=key
        proposals.append({"engine_version":engine,"score_version":scoring,"combined_version":combined,
                          "family":family,"direction":side,"regime":regime,
                          "selected_on_training":selected,"status":status,
                          "train_samples":n,"evaluation_samples":m,
                          "excluded_train":g["excluded_train"],"excluded_evaluation":g["excluded_evaluation"],
                          "training":train_stats,"evaluation_selected_only":evaluation})
    return {"version":VERSION,"symbol":"XAUTUSD","execution_effect":"none",
            "cutoff":cutoff,"as_of":as_of,"cohort":COHORT,"min_train":min_train,"min_evaluation":min_eval,
            "cost_scenarios_bps":[15,30],"exclusions":dict(exclusions),"proposals":proposals,
            "automatic_promotion":False,
            "limitations":["hypothetical normalized-notional outcomes","same-window groups may overlap",
              "complete-case selection can bias results","no statistical significance claim",
              "repeat cutoff selection can contaminate holdout","exposure differs by policy"]}

def read_report(path,*,cutoff,as_of):
    uri=Path(path).resolve().as_uri()+"?mode=ro"
    with sqlite3.connect(uri,uri=True) as db:
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        rows=db.execute("SELECT * FROM gold_v2_windows WHERE signal_boundary<=? ORDER BY signal_boundary",(as_of,)).fetchall()
        return analyze(rows,cutoff=cutoff,as_of=as_of)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal",required=True)
    parser.add_argument("--cutoff",type=int,required=True)
    parser.add_argument("--as-of",type=int,required=True)
    args=parser.parse_args()
    print(json.dumps(read_report(args.journal,cutoff=args.cutoff,as_of=args.as_of),allow_nan=False))
if __name__=="__main__":main()
