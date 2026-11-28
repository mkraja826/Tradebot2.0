"""Supplemental retrospective fee sensitivity, never a change to enrolled outcomes."""
import argparse,json,sqlite3,time
from pathlib import Path
from contextlib import closing
from collections import Counter,defaultdict
from statistics import mean
from .gold_v2_hybrid import MARK_SOURCE
from .gold_v2_hybrid_validation import HORIZON,MAX_GAP
from .gold_v2_quote_management import simulate,POLICIES,COSTS,HISTORICAL_DEMO_COST,VERSION as MANAGEMENT_VERSION

VERSION="gold-v2-fee-review.1"
CALIBRATION={"source":"TB2.0 historical reconciled Gold demo commission report",
             "period_start_utc":1795570567,"period_end_utc_exclusive":1795829767,
             "returned_fee_rates":10,"reported_episodes":29,
             "observed_range_bps":[2.1214640464,2.1364030584],
             "rounded_scenario_bps":2.13,"selection":"returned subset, not an all-trade weighted fee estimate"}

def report(path,*,as_of):
    if type(as_of) is not int or as_of<=0:raise ValueError("invalid_cutoff")
    excluded=Counter();results=[];groups=defaultdict(list)
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        source=db.execute("SELECT source FROM hybrid_study WHERE id=1").fetchone()
        if source is None or source[0]!=MARK_SOURCE:raise ValueError("wrong_study")
        for b,e,eu,raw,status,resolved,outcome in db.execute("""
            SELECT w.boundary,w.enrolled,w.enrolled_us,w.evidence,w.status,o.resolved,o.evidence
            FROM hybrid_windows w LEFT JOIN hybrid_outcomes o ON w.boundary=o.boundary
            WHERE w.boundary<=? ORDER BY w.boundary""",(as_of,)):
            if status!="sampled_outcomes" or resolved is None or resolved>as_of:
                excluded["not_resolved_at_cutoff" if status=="enrolled" or (resolved is not None and resolved>as_of) else status]+=1
                continue
            packet=json.loads(raw);original=json.loads(outcome)
            if (packet.get("signal_source")!=MARK_SOURCE or packet.get("execution_eligible") is not False
                or packet.get("management_version")!=MANAGEMENT_VERSION or original.get("fill_verified") is not False
                or original.get("status")!="sampled_outcomes" or eu is None
                or e<CALIBRATION["period_end_utc_exclusive"]):
                excluded["incompatible_evidence"]+=1;continue
            start=max(eu,packet["quotes"]["demo_quote_timestamp_us"]);end=start+HORIZON*1000000
            if end>as_of*1000000:excluded["incomplete_horizon"]+=1;continue
            rows=db.execute("SELECT stamp,evidence FROM hybrid_quotes WHERE stamp>? AND stamp<=? AND observed<=? ORDER BY stamp",(start,end,end)).fetchall()
            stamps=[start]+[t for t,_ in rows]+[end]
            gap=max(y-x for x,y in zip(stamps,stamps[1:]))/1000000
            if not rows or len(rows)!=original.get("quote_count") or gap>MAX_GAP or gap!=original.get("max_gap_seconds"):
                excluded["coverage_mismatch"]+=1;continue
            samples=[(t,json.loads(q)) for t,q in rows]
            stored={(r["family"],r["direction"]):r for r in original["results"]}
            for plan in packet["hypotheses"]:
                if plan.get("mark_geometry_compatible") is not True:continue
                key=(plan["family"],plan["direction"])
                try:
                    prior=stored[key]["management"]
                    if prior.get("version")!=MANAGEMENT_VERSION:raise ValueError("wrong_management")
                    scenarios={str(c):{p:simulate(plan,samples,policy=p,cost_bps=c) for p in POLICIES}
                               for c in (*COSTS,HISTORICAL_DEMO_COST)}
                    # Require full original management result equality, not only matching net P&L.
                    if any(scenarios[str(c)]!=prior["results"][str(c)] for c in COSTS):
                        raise ValueError("original_replay_mismatch")
                except (ValueError,KeyError,ArithmeticError,TypeError):
                    excluded["candidate_replay_mismatch"]+=1;continue
                model=packet.get("model_version","unversioned")
                results.append({"boundary":b,"model_version":model,"family":key[0],"direction":key[1],"scenarios":scenarios})
                for cost,variants in scenarios.items():
                    for policy,v in variants.items():groups[(model,*key,cost,policy)].append(v["net_bps_initial_notional"])
    summaries=[{"model_version":k[0],"family":k[1],"direction":k[2],"cost_bps":k[3],"policy":k[4],
                "samples":len(v),"positive_samples":sum(x>0 for x in v),"mean_net_bps":mean(v)}
               for k,v in sorted(groups.items())]
    return {"version":VERSION,"as_of":as_of,"symbol":"XAUTUSD","signal_source":MARK_SOURCE,
            "execution_effect":"none","actual_fills":0,"retrospective_supplement":True,
            "calibration":CALIBRATION,"exclusions":dict(excluded),"candidate_count":len(results),
            "window_count":len({r["boundary"] for r in results}),"summaries":summaries,"results":results,
            "limitations":["Historical demo commission scenario, not guaranteed future fees.",
                "Quote-sampled hypothetical outcomes; liquidity, intragap excursions, funding and slippage unverified.",
                "Fee-dependent management is replayed, not merely adjusted after exit.",
                "Original prospective outcomes and learning inputs are unchanged."]}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--journal",required=True);p.add_argument("--as-of",type=int,default=None)
    args=p.parse_args()
    print(json.dumps(report(args.journal,as_of=args.as_of if args.as_of is not None else int(time.time())),indent=2,allow_nan=False))
if __name__=="__main__":main()
