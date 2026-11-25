"""Read-only structured memory from recorded outcomes and decision diagnostics."""
from collections import Counter
from statistics import mean
from .performance import dec
VERSION="learning-memory-v1"
HORIZONS=(900,3600,14400)

def build(symbol,learning,quality):
    facts=[];issues=[];hypotheses=[]
    lessons=learning.get("lessons") or []
    keys={(r.get("decision_id"),r.get("closed")) for r in lessons if r.get("symbol")==symbol}
    for r in lessons:
        n=dec(r.get("net_before_funding"))
        if r.get("symbol")!=symbol or not r.get("decision_id") or n is None:continue
        facts.append({"kind":"reconciled_closed_episode","decision_id":r["decision_id"],"closed":r["closed"],"enrolled":r.get("enrolled"),
            "outcome":"win" if n>0 else "loss" if n<0 else "breakeven","net_before_funding":str(n),"active_rules":r.get("active_rules",[]),
            "evidence_grade":"recorded_observation","source":"outcome-learning/learning.sqlite","causal_claim":False})
    for r in quality.get("findings",[]):
        n=r.get("count")
        if type(n) is not int or n<=0:continue
        success=r["finding"]=="verified_autonomous_mutations"
        item={"kind":r["finding"],"count":n,"basis":r.get("evidence"),"scope":r.get("scope"),
            "evidence_grade":"recorded_observation" if success or n==1 else "repeated_process_observation",
            "source":"decision_quality","causal_claim":False}
        (facts if success else issues).append(item)
    for h in HORIZONS:
        rows=[r for r in learning.get("followups",[]) if r.get("horizon_s")==h and (r.get("decision_id"),r.get("closed")) in keys]
        counts=Counter();returns=[];until=-1;seen=set()
        # Reserve the full window before evaluating its outcome; missing data cannot
        # make an overlapping later observation eligible. Separate enrollment timing.
        for r in sorted(rows,key=lambda v:(v.get("start",0),v.get("decision_id",""),v.get("closed",""))):
            k=(r["decision_id"],r["closed"],h)
            if k in seen:continue
            seen.add(k)
            timing=r.get("timing")
            if timing!="prospective_window":
                counts[timing if timing in ("retrospective_window","partly_elapsed_at_enrollment") else "timing_unknown"]+=1;continue
            a,b=r.get("start"),r.get("finish")
            if type(a) is not int or type(b) is not int or b-a!=h:counts["invalid_window"]+=1;continue
            if a<until:counts["overlap_excluded"]+=1;continue
            until=b
            status=r.get("status")
            value=dec((r.get("evidence") or {}).get("gross_directional_price_return_bps"))
            if status=="observed" and value is not None:
                returns.append(float(value));counts["prospective_observed"]+=1
            else:counts["prospective_"+str(status)]+=1
        hypotheses.append({"kind":"post_exit_direction_continuation","horizon_s":h,"evidence_grade":"unvalidated_hypothesis",
            "counts":dict(counts),"prospective_nonoverlap_samples":len(returns),"mean_gross_directional_bps":mean(returns) if returns else None,
            "positive_count":sum(v>0 for v in returns),"negative_count":sum(v<0 for v in returns),
            "source":"outcome-learning/learning.sqlite","scope":"latest 50 lessons and 150 followups","causal_claim":False})
    return {"version":VERSION,"symbol":symbol,"status":"observed" if learning.get("status")=="observed" and quality.get("status")=="observed" else "incomplete_sources",
        "execution_effect":"none","model_feedback_enabled":False,"verified_observations":facts,"process_observations":issues,"hypotheses":hypotheses,
        "statistically_supported_lessons":[],"statistical_status":"not_validated",
        "limitations":["Repeated process events are not recurring causes of losses.","Only prospective nonoverlapping windows per horizon enter descriptive hypothesis statistics; horizons remain correlated.","No significance test, independent holdout, or executable counterfactual comparison has established a trading lesson.","The durable learning journal is the source; this memory view is derived on read, not model training or automatic feedback."]}
