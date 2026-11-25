"""Descriptive rule overlap and exact shared-quote cohorts; no execution effects."""
import json,sqlite3,math
from collections import Counter,defaultdict
from contextlib import closing
from itertools import combinations
from pathlib import Path
from statistics import mean
from .regime import FAMILIES
from .research import HORIZONS,TOLERANCE
from .planner_shadow import VERSION as SOURCE_VERSION
VERSION="combination-intelligence-v1"
BUCKET=300
COST_BPS=15

def valid_rule(symbol,r):
    return isinstance(r,str) and r in FAMILIES and r.startswith({"BTCUSD":"B","XAUTUSD":"G"}[symbol])

def overlap(symbol,packets):
    counts=Counter();pairs=defaultdict(Counter);buckets=set();rejected=0
    for p in sorted(packets,key=lambda x:x.get("as_of",0)):
        at=p.get("as_of")
        if p.get("symbol")!=symbol or p.get("version")!=SOURCE_VERSION or type(at) is not int or at<=0:rejected+=1;continue
        bucket=at//BUCKET
        if bucket in buckets:continue
        groups=p.get("active_rules")
        if not isinstance(groups,dict) or any(not isinstance(groups.get(k),list) for k in ("LONG","SHORT","CONFLICT")):rejected+=1;continue
        groups={k:set(v for v in groups[k] if valid_rule(symbol,v)) for k in ("LONG","SHORT","CONFLICT")}
        if any(groups[a]&groups[b] for a,b in combinations(groups,2)):rejected+=1;continue
        buckets.add(bucket)
        active=set().union(*groups.values())
        counts.update(active)
        for a,b in combinations(sorted(active),2):
            pair=pairs[a,b];pair["together"]+=1
            if a in groups["CONFLICT"] or b in groups["CONFLICT"]:pair["conflict"]+=1
            elif (a in groups["LONG"])==(b in groups["LONG"]):pair["same"]+=1
            else:pair["opposed"]+=1
    rows=[]
    for (a,b),c in sorted(pairs.items()):
        union=counts[a]+counts[b]-c["together"]
        rows.append({"rules":[a,b],"families":[FAMILIES[a],FAMILIES[b]],"same_family":FAMILIES[a]==FAMILIES[b],
            "a_active":counts[a],"b_active":counts[b],"together":c["together"],"same_direction":c["same"],"opposed_direction":c["opposed"],
            "conflict_involved":c["conflict"],"jaccard":c["together"]/union,
            "same_direction_share_of_directional":c["same"]/(c["same"]+c["opposed"]) if c["same"]+c["opposed"] else None})
    return {"sampled_packets":len(buckets),"input_packets":len(packets),"invalid_packets":rejected,"bucket_s":BUCKET,
        "pair_count":len(rows),"pairs":sorted(rows,key=lambda r:(-r["together"],r["rules"]))}

def cohorts(symbol,observations):
    # Same actual archived mark timestamp, horizon and direction; never infer
    # absent rules or join different quote times. One price path per cohort.
    groups=defaultdict(list)
    for ident,rule,entry_us,h,side,entry,status,exit_us,exit_price,value in observations:
        if not valid_rule(symbol,rule) or h not in HORIZONS or type(entry_us) is not int or entry_us<0 or side not in ("LONG","SHORT"):continue
        groups[entry_us,h,side].append((rule,entry,status,exit_us,exit_price,value))
    by=defaultdict(list);joint=0;invalid=0
    for (at,h,side),rows in sorted(groups.items()):
        ids=tuple(sorted({r[0] for r in rows}))
        if len(ids)<2:continue
        joint+=1
        # All rows must agree on the same shared price path and observed status.
        entries={r[1] for r in rows};states={r[2] for r in rows}
        status="pending" if states=={"pending"} else "missed" if states=={"missed"} else "invalid_or_incomplete"
        value=None
        if states=={"observed"} and len(entries)==1:
            e=rows[0][1];end=rows[0][3];x=rows[0][4];v=rows[0][5]
            if type(end) is int and at+h*1000000<=end<=at+(h+TOLERANCE)*1000000 and all(type(z) in (int,float) and math.isfinite(z) for z in (e,x,v)) and e>0 and x>0:
                expected=(x/e-1)*10000*(1 if side=="LONG" else -1)
                if all(r[3]==end and r[4]==x and type(r[5]) in (int,float) and math.isfinite(r[5]) and abs(r[5]-expected)<=1e-6 for r in rows):
                    status="observed";value=expected-COST_BPS
        if status=="invalid_or_incomplete":invalid+=1
        for a,b in combinations(ids,2):
            by[(a,b,h)].append((at,side,status,value))
    out=[]
    for (a,b,h),rows in sorted(by.items()):
        counts=Counter();returns=[];until=-1
        for at,side,status,value in sorted(rows):
            counts[status]+=1
            if at<until:counts["overlap_excluded"]+=1;continue
            until=at+(h+TOLERANCE)*1000000
            if status=="observed":returns.append(value)
        out.append({"rules":[a,b],"families":[FAMILIES[a],FAMILIES[b]],"horizon_s":h,"raw_counts":dict(counts),
            "valid_nonoverlap_samples":len(returns),"mean_net_bps":mean(returns) if returns else None,
            "positive_rate":sum(x>0 for x in returns)/len(returns) if returns else None})
    return {"joint_cohorts":joint,"invalid_or_incomplete_cohorts":invalid,"pair_horizon_count":len(out),
        "pair_horizons":sorted(out,key=lambda r:(-r["valid_nonoverlap_samples"],r["rules"],r["horizon_s"]))}

def build(symbol,packets,observations):
    return {"version":VERSION,"symbol":symbol,"status":"observed","execution_effect":"none","validation":"descriptive_only","assumed_cost_bps":COST_BPS,
        "overlap":overlap(symbol,packets),"joint_research":cohorts(symbol,observations),
        "limitations":["First archived snapshot per five-minute bucket, not continuous observation; active rule counts include conflicts.",
        "Jaccard is co-activation overlap, not causal redundancy, return correlation or proof of independent confirmations.",
        "Joint cohorts contain newly enrolled signals sharing exact mark timestamp, side and horizon; they do not prove other rules were absent.",
        "One shared price return per cohort and pair; nonoverlap selected across directions before outcome inspection. Cross-pair samples overlap.",
        "Assumed 15 bps costs; no actual fills, causal complementarity, strategy ranking or weight change."]}

def report(root,symbol):
    root=Path(root)
    try:
        def connect(name):return sqlite3.connect((root/name).resolve().as_uri()+"?mode=ro",uri=True,timeout=2)
        with closing(connect("planner_shadow.sqlite")) as db:
            packets=[json.loads(r) for r, in db.execute("SELECT payload FROM planner_packets WHERE symbol=? AND version=? ORDER BY as_of",(symbol,SOURCE_VERSION))]
        with closing(connect("signal_research.sqlite")) as db:
            rows=db.execute("SELECT id,rule_id,entry_us,horizon_s,side,entry,status,exit_us,exit,return_bps FROM observations WHERE symbol=?",(symbol,)).fetchall()
        return build(symbol,packets,rows)
    except (sqlite3.Error,ValueError,TypeError,KeyError,AttributeError,ArithmeticError):
        return {"version":VERSION,"symbol":symbol,"status":"unavailable","execution_effect":"none"}
