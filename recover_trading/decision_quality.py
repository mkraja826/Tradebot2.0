"""Observed decision-quality evidence. No model training or execution changes."""
from collections import Counter
from .performance import dec
VERSION="decision-quality-v1"

def report(review,performance,excursions,submission,management):
    rows=review.get("recent") or []
    filled=[r for r in rows if r.get("filled_contracts") is not None]
    closed=[r for r in filled if r.get("outcome")=="closed_reconciled" and dec(r.get("net_before_funding")) is not None]
    deviations=[dec(r.get("entry_deviation_bps")) for r in filled];deviations=[v for v in deviations if v is not None]
    geometry=[r for r in filled if dec(r.get("fill_stop_bps")) is not None and dec(r.get("fill_target_bps")) is not None]
    invalid=[r for r in geometry if dec(r["fill_stop_bps"])<=0 or dec(r["fill_target_bps"])<=0]
    x=[r for r in excursions.get("episodes",[]) if r.get("decision_id") and r.get("status")=="complete_interior_lower_bound"]
    actual=performance.get("recover_attributed") or {}
    unknown=(submission.get("by_decision_position") or {}).get("unknown") or {}
    actions=management.get("actions") or {}
    mutations=management.get("autonomous_attempts") or []
    findings=[]
    def add(name,count,basis,scope):
        findings.append({"finding":name,"count":count,"evidence":basis,"scope":scope})
    add("provider_or_validation_failures",review.get("outcome_counts",{}).get("decision_failed"),"failed decision requests; not losing trades","all archived decisions")
    add("unknown_submissions_with_existing_position_context",sum(unknown.get(k,0) for k in ("long","short","mixed")) if submission.get("status")=="observed" else None,"position at decision time; causality not established","all archived submissions")
    add("adverse_entry_reference_deviation",sum(v>0 for v in deviations),"signed deviation from AI reference; not measured market slippage","latest 100 decision records")
    add("planned_bracket_incompatible_with_observed_fill",len(invalid),"original planned stop or target not on correct side of weighted fill; not current exchange bracket","latest 100 decision records")
    add("verified_autonomous_mutations",sum(r.get("count",0) for r in mutations if r.get("status")=="verified") if management.get("status")=="observed" else None,"exchange-state reconciliation, not proven exit improvement","all archived management attempts")
    return {"version":VERSION,"status":"observed" if review.get("status")=="observed" else "review_unavailable","execution_effect":"none",
        "closed_outcome_evidence":"insufficient_for_recurring_loss_attribution",
        "closed_recover_episodes":actual.get("closed_episodes"),"closed_recover_losses":actual.get("losses_before_funding"),"closed_recover_net_before_funding":actual.get("net_before_funding"),
        "decision_window_count":len(rows),"filled_decision_samples":len(filled),"entry_deviation_samples":len(deviations),"fill_geometry_samples":len(geometry),"matched_closed_decision_samples":len(closed),"complete_attributed_excursion_samples":len(x),
        "management_proposal_actions":actions,"findings":findings,"invalid_geometry_decision_ids":[r["id"] for r in invalid],
        "limitations":["No inference of causal mistakes from a small or incomplete sample.","Historical and unattributed trades excluded from Recover outcomes.","Management amendments are not closed trades or proven profit improvements.","No automatic strategy weighting, retraining or order changes."]}
