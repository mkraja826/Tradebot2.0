"""Chronological mark-hybrid research report. No strategy mutations."""
import argparse,json,sqlite3,os,tempfile
from collections import defaultdict,Counter
from math import isfinite
from pathlib import Path
from statistics import mean,median
from .gold_v2_hybrid import MARK_SOURCE
from .gold_v2_quote_management import VERSION as MANAGEMENT_VERSION,POLICIES
from .gold_v2_learning import metrics

VERSION="gold-v2-mark-learning.1"
COSTS=("15","30")
MIN_TRAIN=30
MIN_HOLDOUT=20

def extract(row):
    evidence=json.loads(row["evidence"]);outcome=json.loads(row["outcome"])
    if evidence.get("signal_source")!=MARK_SOURCE or evidence.get("execution_eligible") is not False or outcome.get("fill_verified") is not False:
        return [],"wrong_cohort"
    if evidence.get("management_version")!=MANAGEMENT_VERSION:return [],"different_management_version"
    model=evidence.get("model_version")
    if model not in ("gold-v2-mark-model.1","gold-v2-mark-model.2"):return [],"unknown_model"
    if outcome.get("status")!="sampled_outcomes":return [],"no_sampled_outcomes"
    groups={(x["family"],x["direction"]):x["macro_group"] for x in evidence.get("macro_annotation",{}).get("candidate_groups",[])}
    samples=[];seen=set()
    for p in outcome.get("results",[]):
        family,side=p["family"],p["direction"]
        if side not in ("LONG","SHORT") or (family,side) in seen:raise ValueError("invalid_candidate_identity")
        seen.add((family,side))
        management=p.get("management",{})
        values={}
        if management.get("version")==MANAGEMENT_VERSION:
            for cost in COSTS:
                variants=management.get("results",{}).get(cost,{})
                v={k:variants.get(k,{}).get("net_bps_initial_notional") for k in POLICIES}
                if all(type(x) in (int,float) and isfinite(x) and variants[k].get("fill_verified") is False for k,x in v.items()):
                    values[cost]=v
        macro=groups.get((family,side),"unknown")
        if macro not in ("aligned","opposed","neutral","unknown"):macro="unknown"
        samples.append({"model":model,"family":family,"direction":side,"macro":macro,
                        "values":values if len(values)==len(COSTS) else None})
    return samples,None

def analyze(rows,*,cutoff,as_of,min_train=MIN_TRAIN,min_holdout=MIN_HOLDOUT):
    if any(type(x) is not int for x in (cutoff,as_of,min_train,min_holdout)) or not 0<cutoff<as_of or min(min_train,min_holdout)<1:
        raise ValueError("invalid_study_bounds")
    groups=defaultdict(lambda:{"train":[],"holdout":[],"excluded_train":0,"excluded_holdout":0})
    excluded=Counter();seen=set();last_end=0
    for row in sorted(rows,key=lambda r:r["boundary"]):
        b,e,r=(row[k] for k in ("boundary","enrolled","resolved"))
        if b in seen:raise ValueError("duplicate_window")
        seen.add(b)
        if any(type(x) is not int for x in (b,e,r)) or not b<=e<b+300 or not e+3600<=r<=as_of:
            excluded["not_resolved_at_cutoff"]+=1;continue
        if e<last_end:raise ValueError("overlapping_sample_windows")
        last_end=e+3600
        if b<cutoff and r<cutoff:phase="train"
        elif b>=cutoff:phase="holdout"
        else:excluded["crosses_cutoff"]+=1;continue
        samples,reason=extract(row)
        if reason:excluded[reason]+=1;continue
        for s in samples:
            # Report all technical samples and separate macro strata. These overlap.
            for macro in ("all",s["macro"]):
                key=(s["model"],s["family"],s["direction"],macro)
                g=groups[key]
                if s["values"] is None:g["excluded_"+phase]+=1
                else:g[phase].append(s)
    proposals=[]
    for key,g in sorted(groups.items()):
        train,hold=g["train"],g["holdout"]
        training={p:{c:metrics(train,p,c) for c in COSTS} for p in POLICIES}
        chosen="fixed";status="insufficient_training"
        if len(train)>=min_train:
            eligible=[p for p in POLICIES if p!="fixed" and all(training[p][c]["mean_net_bps"]>0 and training[p][c]["mean_paired_difference_bps"]>0 for c in COSTS)]
            if eligible:
                chosen=max(eligible,key=lambda p:(training[p]["15"]["mean_paired_difference_bps"],p))
                status="awaiting_holdout"
            else:status="no_training_improvement"
        evaluation={c:metrics(hold,chosen,c) for c in COSTS}
        if chosen!="fixed" and len(hold)>=min_holdout:
            status="positive_holdout_observation" if all(evaluation[c]["mean_net_bps"]>0 and evaluation[c]["mean_paired_difference_bps"]>0 for c in COSTS) else "holdout_not_confirmed"
        proposals.append({"model_version":key[0],"family":key[1],"direction":key[2],"macro_group":key[3],
                          "selected_on_training":chosen,"status":status,"train_samples":len(train),"holdout_samples":len(hold),
                          "excluded_train":g["excluded_train"],"excluded_holdout":g["excluded_holdout"],
                          "training":training,"holdout_selected_only":evaluation})
    # Entry family ranking uses only the fixed-policy training baseline, not holdout results.
    ranking=[]
    for p in proposals:
        if p["macro_group"]!="all" or p["train_samples"]<min_train:continue
        t=p["training"]["fixed"]
        ranking.append({"model_version":p["model_version"],"family":p["family"],"direction":p["direction"],
                        "train_samples":p["train_samples"],"mean_net_bps_15":t["15"]["mean_net_bps"],
                        "mean_net_bps_30":t["30"]["mean_net_bps"]})
    ranking.sort(key=lambda p:(-p["mean_net_bps_30"],p["model_version"],p["family"],p["direction"]))
    return {"version":VERSION,"symbol":"XAUTUSD","signal_source":MARK_SOURCE,"execution_effect":"none",
            "automatic_promotion":False,"cutoff":cutoff,"as_of":as_of,"min_train":min_train,"min_holdout":min_holdout,
            "exclusions":dict(excluded),"training_entry_ranking":ranking,"proposals":proposals,
            "limitations":["hypothetical quote-sampled outcomes","overlapping candidate/stratum groups",
                "no causal macro inference","complete-case selection bias","no statistical significance claim",
                "repeated cutoff selection can contaminate holdout","not account equity or verified fills"]}

def read_report(path,*,cutoff,as_of):
    with sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True) as db:
        db.row_factory=sqlite3.Row;db.execute("PRAGMA query_only=ON")
        source=db.execute("SELECT source FROM hybrid_study WHERE id=1").fetchone()
        if source is None or source[0]!=MARK_SOURCE:raise ValueError("wrong_study")
        rows=db.execute("""SELECT w.boundary,w.enrolled,w.evidence,o.resolved,o.evidence AS outcome
            FROM hybrid_windows w JOIN hybrid_outcomes o ON w.boundary=o.boundary
            WHERE w.boundary<=? ORDER BY w.boundary""",(as_of,)).fetchall()
        return analyze(rows,cutoff=cutoff,as_of=as_of)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--journal",required=True);p.add_argument("--cutoff",type=int,required=True);p.add_argument("--as-of",type=int,required=True)
    p.add_argument("--publish-dir",help="Atomically publish a read-only dashboard snapshot")
    args=p.parse_args()
    result=read_report(args.journal,cutoff=args.cutoff,as_of=args.as_of)
    raw=json.dumps(result,allow_nan=False)
    if args.publish_dir:
        root=Path(args.publish_dir)
        fd,tmp=tempfile.mkstemp(prefix="mark_learning_",dir=root)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as stream:stream.write(raw)
            os.replace(tmp,root/"mark_learning_status.json")
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    print(raw)
if __name__=="__main__":main()
