"""Read-only paid paper receipt review and counterfactual signal observations."""
import json
from collections import Counter,defaultdict
from statistics import mean
from pathlib import Path
from contextlib import closing
from tradebot.decision_experience_v3 import ro
from tradebot.opportunity_journal_v3 import ROUTE,digest
from tradebot.model_wire_v3 import MODEL_IDS
from tradebot.signal_learning_v3 import evaluate_event
from tradebot.research_collector_v3 import atomic_json

def link(e,r,key,s,reserved,h,now):
    if (r["event_id"],r["symbol"],r["request_sha256"],r["model"])!=(key,s,h,MODEL_IDS[s]):
        raise ValueError("receipt_identity")
    if r["status"]!="validated_paper_proposal" or r["execution_authorized"] is not False or r["orders_submitted"]!=0 or r["account_basis"]!="hypothetical":
        raise ValueError("not_paper")
    if (e["event_id"],e["symbol"],e["model_if_enabled"])!=(key,s,ROUTE[s]):
        raise ValueError("event_identity")
    if not e["as_of"]<=reserved<=r["checked_at"]<=min(now,e["as_of"]+150):
        raise ValueError("invalid_time")
    a=r["decision"]
    if (a["event_id"],a["symbol"])!=(key,s) or a["action"] not in ("WAIT","LONG","SHORT"):
        raise ValueError("decision_identity")
    if (a["action"]=="WAIT")!=(a["plan"] is None):raise ValueError("decision_shape")
    return a

def summarize(records):
    groups=defaultdict(list)
    for r in records:
        for o in r["signal_paths"]:
            groups[(r["symbol"],r["action"],o["horizon_minutes"])].append(o)
    out=[]
    for (s,a,h),rows in sorted(groups.items()):
        observed=[o for o in rows if o["status"]=="observed"]
        values=[o["directional_return_pct"] for o in observed]
        out.append({"symbol":s,"decision_action":a,"horizon_minutes":h,
                    "observed":len(values),"pending":sum(o["status"]=="pending" for o in rows),
                    "missing":sum(o["status"]=="missing_candles" for o in rows),
                    "mean_signal_direction_return_pct":mean(values) if values else None,
                    "positive_signal_fraction":sum(v>0 for v in values)/len(values) if values else None,
                    "distinct_observed_events":len({o["event_id"] for o in observed}),
                    "scope":"overlapping_signal_paths_not_trade_returns",
                    "model_quality":None,"actual_trade_outcome":False})
    return out

def report(root,*,now):
    root=Path(root)
    out={"mode":"paper_learning_diagnostic_only","checked_at":now,"execution_authorized":False,"orders_submitted":0,"paid_ai_requests":0,"verified_trade_outcomes":0,"markets":{},"request_provenance":"receipt_hash_only","records":[]}
    with closing(ro(root/"m19-provider-campaign-v3.sqlite")) as source,closing(ro(root/"opportunities-v3.sqlite")) as events,closing(ro(root/"market-v3.sqlite")) as market:
        source.execute("BEGIN")
        limit=source.execute("SELECT request_limit FROM budget WHERE id=1").fetchone()[0]
        rows=source.execute("SELECT event_id,symbol,reserved_at,request_hash,state,receipt FROM requests ORDER BY reserved_at,event_id LIMIT 21").fetchall()
        if limit!=20 or len(rows)>limit:raise ValueError("budget_mismatch")
        out["reserved"]=len(rows);out["limit"]=limit
        def bars(s,a,b):
            return [json.loads(x[0]) for x in market.execute("SELECT payload FROM samples WHERE symbol=? AND series='candle:5m' AND stamp>=? AND stamp<? ORDER BY stamp",(s,a,b))]
        for s in ROUTE:
            counts=Counter()
            for key,sym,at,h,state,raw in rows:
                if sym!=s:continue
                counts[state]+=1
                if state!="validated_paper_proposal":continue
                try:
                    r=json.loads(raw);e=json.loads(events.execute("SELECT payload FROM events WHERE event_id=? AND symbol=?",(key,s)).fetchone()[0])
                    a=link(e,r,key,s,at,h,now)
                    obs=evaluate_event(e,bars,now=now)
                    item={"event_id":key,"symbol":s,"action":a["action"],"receipt_sha256":digest(r),"signal_paths":obs,"actual_trade_outcome":False,
                          "proposal_outcome":"not_applicable_wait" if a["action"]=="WAIT" else "limit_fill_not_modelled" if a["plan"]["entry_type"]=="LIMIT" else "not_evaluated"}
                    out["records"].append(item);counts[a["action"]]+=1
                    for o in obs:counts["path_"+o["status"]]+=1
                except (ValueError,TypeError,KeyError,AttributeError,IndexError):counts["unlinked"]+=1
            out["markets"][s]=dict(counts)
    out["signal_path_summary"]=summarize(out["records"])
    atomic_json(root/"m21-paper-learning-v3.json",out)
    return out


if __name__=="__main__":
    import argparse,time
    parser=argparse.ArgumentParser()
    parser.add_argument("--directory",required=True)
    args=parser.parse_args()
    r=report(args.directory,now=int(time.time()))
    print("reserved",r["reserved"],"linked",len(r["records"]),"markets",r["markets"])
