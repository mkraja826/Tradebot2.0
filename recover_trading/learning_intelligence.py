"""Offline prospective learning experiment and bounded evidence packet.

No provider requests, execution, prompt changes or automatic policy promotion.
"""
import argparse
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from statistics import mean
from .performance import dec, stamp
from .regime import FAMILIES
from .trade_intelligence import sql, obj, mapping

VERSION="learning-intelligence-v1"
SYMBOLS={"BTCUSD":"B","XAUTUSD":"G"}
MIN_RESEARCH_SAMPLE=20

def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)

def digest(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()

def clean(symbol,rows,cutoff):
    """Only reconciled observations already enrolled before cutoff."""
    if symbol not in SYMBOLS or type(cutoff) is not int or cutoff<=0:raise ValueError("invalid cutoff")
    out=[];seen=set();counts=Counter()
    for ident,closed,enrolled,raw in rows or []:
        d=obj(raw);opened=stamp({"created_at":d.get("opened")});end=stamp({"created_at":closed})
        n,g,f=map(dec,(d.get("net_before_funding"),d.get("gross_pnl"),d.get("fees")))
        rules=d.get("active_rules")
        if (type(enrolled) is not int or enrolled>=cutoff or opened is None or end is None
            or not opened<end or end.timestamp()>enrolled
            or not isinstance(ident,str) or not re.fullmatch("[a-f0-9]{64}",ident)
            or d.get("decision_id")!=ident or d.get("symbol")!=symbol or d.get("closed")!=closed
            or d.get("learning_status")!="observation_only" or d.get("execution_effect")!="none"
            or d.get("direction") not in ("LONG","SHORT") or not isinstance(rules,list)
            or any(not isinstance(r,str) or not r.startswith(SYMBOLS[symbol]) or r not in FAMILIES for r in rules)
            or None in (n,g,f) or g-f!=n):
            counts["excluded_invalid_or_not_yet_known"]+=1;continue
        k=(ident,closed)
        if k in seen:
            counts["duplicate"]+=1;continue
        seen.add(k)
        out.append({"decision_id":ident,"opened":d["opened"],"closed":closed,"enrolled":enrolled,
            "direction":d["direction"],"rules":sorted(set(rules)),"net_before_funding":str(n),
            "outcome":"win" if n>0 else "loss" if n<0 else "breakeven"})
    return sorted(out,key=lambda r:(r["enrolled"],r["decision_id"],r["closed"])),dict(counts)

def read_rows(path,symbol):
    return sql(Path(path),"SELECT decision_id,closed,enrolled,payload FROM lessons WHERE symbol=?",(symbol,))

def cohort(rows,rule,direction):
    def metrics(rs):
        vals=[dec(r["net_before_funding"]) for r in rs]
        return {"samples":len(vals),"wins":sum(v>0 for v in vals),
            "win_rate":sum(v>0 for v in vals)/len(vals) if vals else None,
            "mean_net_before_funding":str(sum(vals)/len(vals)) if vals else None}
    same=[r for r in rows if r["direction"]==direction]
    a=metrics([r for r in same if rule in r["rules"]])
    b=metrics([r for r in same if rule not in r["rules"]])
    return {"rule_present":a,"same_direction_rule_absent":b,
        "win_rate_difference":a["win_rate"]-b["win_rate"] if a["win_rate"] is not None and b["win_rate"] is not None else None}

def freeze(symbol,rows,cutoff,rule,direction,expected):
    if (symbol not in SYMBOLS or not isinstance(rule,str) or not rule.startswith(SYMBOLS[symbol])
        or rule not in FAMILIES or direction not in ("LONG","SHORT") or expected not in ("higher","lower")):
        raise ValueError("invalid single predeclared hypothesis")
    if rows is None:raise ValueError("journal unavailable")
    dev,_=clean(symbol,rows,cutoff)
    plan={"version":VERSION,"symbol":symbol,"registered_at":cutoff,"rule":rule,"direction":direction,
        "expected_win_rate_difference":expected,"development_digest":digest(dev),
        "development":cohort(dev,rule,direction),"minimum_samples_per_cohort_per_period":MIN_RESEARCH_SAMPLE,
        "endpoint":"observed_net_win_frequency_rule_present_minus_same_direction_rule_absent"}
    return {**plan,"plan_digest":digest(plan)}

def evaluate(plan,rows,cutoff):
    if not isinstance(plan,dict):raise ValueError("invalid plan")
    body={k:v for k,v in plan.items() if k!="plan_digest"}
    if plan.get("plan_digest")!=digest(body) or plan.get("version")!=VERSION:raise ValueError("plan checksum mismatch")
    at=plan.get("registered_at")
    if type(at) is not int or type(cutoff) is not int or cutoff<=at:raise ValueError("holdout must follow registration")
    if rows is None:return {"status":"journal_unavailable","validated_lessons":[],"execution_effect":"none"}
    baseline=freeze(plan["symbol"],rows,at,plan["rule"],plan["direction"],plan["expected_win_rate_difference"])
    if baseline!=plan:raise ValueError("development snapshot changed")
    known,excluded=clean(plan["symbol"],rows,cutoff)
    prior=[r for r in known if r["enrolled"]<at]
    hold=[r for r in known if r["enrolled"]>=at and stamp({"created_at":r["opened"]}).timestamp()>at]
    dev=cohort(prior,plan["rule"],plan["direction"]);test=cohort(hold,plan["rule"],plan["direction"])
    enough=all(period[k]["samples"]>=MIN_RESEARCH_SAMPLE for period in (dev,test) for k in ("rule_present","same_direction_rule_absent"))
    sign=1 if plan["expected_win_rate_difference"]=="higher" else -1
    agrees=lambda x:x["win_rate_difference"] is not None and x["win_rate_difference"]*sign>0
    status="insufficient_samples" if not enough else "descriptive_replication" if agrees(dev) and agrees(test) else "hypothesis_not_replicated"
    return {"version":VERSION,"symbol":plan["symbol"],"status":status,"as_of":cutoff,
        "plan_digest":plan["plan_digest"],"development":dev,"holdout":test,"excluded":excluded,
        "holdout_eligible_episodes":len(hold),"validated_lessons":[],"causal_validation":False,
        "execution_effect":"none","limitations":["Plan checksum detects edits but is not proof of an independently timestamped registration.",
            "Only episodes opened strictly after registration and enrolled before report cutoff enter holdout.",
            "Win frequency is not net expectancy; monetary averages are descriptive and confounded by size.",
            "The comparison does not control all strategy co-occurrences or changing regimes.",
            "Research sample minimum is not a trading gate or a statistical significance claim.",
            "No automatic lesson promotion or model retraining."]}

def feedback(symbol,rows,cutoff):
    known,excluded=clean(symbol,rows,cutoff)
    return {"version":VERSION,"symbol":symbol,"as_of":cutoff,
        "status":"journal_unavailable" if rows is None else "observations_available" if known else "no_prior_evidence",
        "observations":list(reversed(known[-8:])),"excluded":excluded,
        "validated_lessons":[],"causal_validation":False,"execution_effect":"none",
        "policy":"offline review only; outcomes are historical observations, not trading instructions"}

def main():
    p=argparse.ArgumentParser();p.add_argument("--journal",required=True,type=Path)
    p.add_argument("--symbol",required=True,choices=SYMBOLS);p.add_argument("--mode",required=True,choices=("freeze","evaluate","feedback"))
    p.add_argument("--rule");p.add_argument("--direction",choices=("LONG","SHORT"));p.add_argument("--expected",choices=("higher","lower"))
    p.add_argument("--plan",type=Path);a=p.parse_args();now=int(time.time())
    rows=read_rows(a.journal,a.symbol)
    if a.mode=="freeze":out=freeze(a.symbol,rows,now,a.rule,a.direction,a.expected)
    elif a.mode=="evaluate":
        if a.plan is None:p.error("--plan is required")
        plan=json.loads(a.plan.read_text())
        if plan.get("symbol")!=a.symbol:p.error("plan symbol mismatch")
        out=evaluate(plan,rows,now)
    else:out=feedback(a.symbol,rows,now)
    print(json.dumps(out,allow_nan=False,indent=2))
if __name__=="__main__":main()
