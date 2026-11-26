"""Read-only trade intelligence evidence ledger; never calls AI or broker."""
import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from .performance import dec, stamp, read_performance
from .decision_review import read_review
from .trade_excursion import report as excursion_report
from .outcome_learning import report as learning_report

VERSION = "trade-intelligence-v1"
SYMBOLS = ("BTCUSD", "XAUTUSD")

def obj(raw):
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}

def mapping(v):
    return v if isinstance(v, dict) else {}

def sql(path, query, args):
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            return db.execute(query,args).fetchall()
    except sqlite3.Error:
        return None

def fields(d, keys):
    return {k:d.get(k) for k in keys}

def metrics(d):
    d=mapping(d);u=mapping(d.get("usage"))
    return {**fields(d,("elapsed_ms","finish_reason")), "usage":fields(u,("prompt_tokens","completion_tokens","total_tokens"))}

def episode_key(e):
    return (e.get("decision_id"),e.get("opened"),e.get("closed"))

def unique_match(items, predicate):
    found=[x for x in items if predicate(x)]
    return found[0] if len(found)==1 else None

def money(value):
    return str(value) if value is not None else None

def exposure(context, result, review):
    product=mapping(mapping(context.get("demo_account")).get("product"))
    qty=dec(review.get("filled_contracts"))
    fill=dec(review.get("average_fill_price"))
    sl=dec(result.get("stop_loss"))
    tp=dec(result.get("take_profit"))
    cv=dec(product.get("contract_value"))
    leverage=dec(result.get("leverage"))
    currency=mapping(product.get("settling_asset")).get("symbol")
    out={"currency":currency,"planned_contracts":result.get("size"),
         "filled_contracts":money(qty),"planned_capital_allocation":money(dec(result.get("capital_allocation"))),
         "leverage":money(leverage),"contract_value":money(cv),"average_fill_price":money(fill),
         "fill_notional":None,"estimated_initial_margin_excluding_fees":None,
         "planned_stop_loss_amount_at_fill":None,"planned_target_gain_at_fill":None,
         "basis":"linear_contract_estimate_not_actual_margin_or_verified_bracket"}
    if (product.get("notional_type")!="vanilla" or not currency
        or currency!=mapping(product.get("quoting_asset")).get("symbol")
        or any(v is None or v<=0 for v in (qty,fill,cv,leverage))):
        return out
    out["fill_notional"]=money(qty*fill*cv)
    out["estimated_initial_margin_excluding_fees"]=money(qty*fill*cv/leverage)
    sign=1 if result.get("side")=="buy" else -1 if result.get("side")=="sell" else None
    if sign and sl is not None and sl>0 and sign*(fill-sl)>0:
        out["planned_stop_loss_amount_at_fill"]=money(sign*(fill-sl)*qty*cv)
    if sign and tp is not None and tp>0 and sign*(tp-fill)>0:
        out["planned_target_gain_at_fill"]=money(sign*(tp-fill)*qty*cv)
    return out

def management_candidates(ep, records):
    opened=stamp({"created_at":ep.get("opened")})
    closed=stamp({"created_at":ep.get("closed")})
    if not opened or not closed or closed<=opened:
        return []
    out=[]
    for ident,created,model,status,raw_c,raw_r,attempt_at,action,attempt_status,raw_a in records or []:
        # Integer-second journal times are ambiguous at episode boundaries.
        if type(created) is not int or not opened.timestamp()<created<closed.timestamp():
            continue
        c=obj(raw_c);r=obj(raw_r);p=mapping(r.get("proposal"));a=obj(raw_a)
        position=mapping(c.get("position"))
        direction={"long":"LONG","short":"SHORT"}.get(position.get("direction"))
        if direction!=ep.get("direction"):
            continue
        same_identity=bool(c.get("execution_identity")) and c.get("execution_identity")==a.get("identity")
        linked=(attempt_at is not None and type(attempt_at) is int and created<=attempt_at<=closed.timestamp()
                and same_identity and action==p.get("action"))
        out.append({"proposal_id":ident,"created":created,"model":model,"status":status,
                    "action":p.get("action"),"reason":p.get("reason"),
                    "proposed_stop":p.get("stop_loss"),"proposed_target":p.get("take_profit"),
                    "proposed_reduction":p.get("contracts"),"metrics":metrics(r.get("diagnostics")),
                    "position_size":position.get("size"),"position_entry":position.get("entry_price"),
                    "association":"time_and_direction_candidate_not_proven_episode_identity",
                    "attempt":{"created":attempt_at,"status":attempt_status,"amended_leg":a.get("amended_leg"),
                               "evidence_status":mapping(a.get("evidence")).get("status"),
                               "proposal_identity_match":linked,"journal_verified":linked and attempt_status=="verified"}
                               if attempt_at is not None else None})
    return out

def build(symbol, performance, review, excursions, learning, decisions, management):
    counts=Counter();rows=[]
    episodes=[e for e in performance.get("recent_episodes",[]) if e.get("attribution")=="single_recover_entry_order"]
    for e in episodes:
        ident=e.get("decision_id");key=episode_key(e)
        d=unique_match(decisions or [],lambda x:x[0]==ident)
        rv=unique_match(review.get("recent",[]),lambda x:x.get("id")==ident and x.get("outcome")=="closed_reconciled"
                        and dec(x.get("net_before_funding"))==dec(e.get("net_before_funding")))
        x=unique_match(excursions.get("episodes",[]),lambda x:episode_key(x)==key)
        lesson=unique_match(learning.get("lessons",[]),lambda x:episode_key(x)==key and
                            dec(x.get("net_before_funding"))==dec(e.get("net_before_funding")))
        issues=[]
        if not d:issues.append("entry_decision_missing_or_ambiguous")
        if not rv:issues.append("entry_fill_review_missing_or_ambiguous")
        if not x:issues.append("excursion_missing_or_ambiguous")
        if not lesson:issues.append("learning_missing_or_ambiguous")
        c=obj(d[3]) if d else {};r=obj(d[4]) if d else {}
        if d and (d[2]!="proposed" or r.get("action")!="trade" or r.get("symbol")!=symbol):
            issues.append("entry_decision_not_matching_trade");d=None;c={};r={}
        if x:
            mfe=dec(x.get("mfe_bps"));mae=dec(x.get("mae_bps"))
            if any(v is not None and v>=1000 for v in (mfe,mae)):
                issues.append("large_excursion_requires_data_review")
            if x.get("status")!="complete_interior_lower_bound":
                issues.append("incomplete_excursion_coverage")
        if rv and dec(rv.get("fill_target_bps")) is not None and dec(rv["fill_target_bps"])<=0:
            issues.append("target_beyond_fill_in_wrong_direction")
        if rv and dec(rv.get("fill_stop_bps")) is not None and dec(rv["fill_stop_bps"])<=0:
            issues.append("stop_beyond_fill_in_wrong_direction")
        if management is None:issues.append("management_journal_unavailable")
        ex=exposure(c,r,rv or {})
        if ex["fill_notional"] is None:issues.append("exposure_not_verified")
        net=dec(e.get("net_before_funding"));gross=dec(e.get("gross_pnl"));fees=dec(e.get("fees"))
        if None in (net,gross,fees) or gross-fees!=net:issues.append("pnl_identity_mismatch")
        if net is not None and gross is not None and net<0<gross:issues.append("fees_exceeded_gross_gain")
        counts.update(issues)
        rows.append({"decision_id":ident,"opened":e.get("opened"),"closed":e.get("closed"),"direction":e.get("direction"),
            "entry":{"model":d[1] if d else None,"reason":r.get("reason"),"rules":e.get("active_rules",[]),
                     "plan":fields(r,("entry_reference","stop_loss","take_profit")),
                     "fill_review":fields(rv or {},("entry_deviation_bps","fill_stop_bps","fill_target_bps","entry_attribution")),
                     "metrics":metrics(r.get("diagnostics"))},
            "exposure":ex,"outcome":fields(e,("gross_pnl","fees","net_before_funding","reported_funding","fills")),
            "excursion":fields(x or {},("status","coverage","mfe_bps","mae_bps","gross_weighted_exit_return_bps",
                                         "observed_favorable_gap_bps")),
            "management_candidates":management_candidates(e,management),
            "learning_status":lesson.get("learning_status") if lesson else None,
            "data_quality_notes":issues})
    expected=mapping(performance.get("recover_attributed")).get("closed_episodes")
    return {"version":VERSION,"symbol":symbol,"execution_effect":"none","status":performance.get("status"),
            "coverage":{"expected_attributed_episodes":expected,"reported_episodes":len(rows),
                        "complete_window":type(expected) is int and expected==len(rows),
                        "decision_journal_available":decisions is not None,"management_journal_available":management is not None},
            "data_quality_counts":dict(counts),"trades":rows,
            "limitations":["Read-only bounded recent performance window (up to 50 account episodes); independent journal snapshots may differ.",
              "Recorded AI explanations are not proven causal reasoning.",
              "Management association is time and direction only; attempt verification refers to its proposal, not proven episode identity.",
              "Large excursion flags require source validation; they do not prove bad data.",
              "Planned exposure is an estimate, not actual margin, funding-inclusive P&L, or verified exchange trigger coverage.",
              "No strategy weights, execution policy, learning feedback or orders are changed."]}

def report(root,symbol,learning_dir):
    if symbol not in SYMBOLS:raise ValueError("unsupported symbol")
    root=Path(root)
    p=read_performance(root,symbol)
    r=read_review(root,symbol,p)
    x=excursion_report(root,symbol,p)
    l=learning_report(learning_dir,symbol)
    d=sql(root/"decisions.sqlite","SELECT id,model,status,context,result FROM decisions WHERE symbol=?",(symbol,))
    m=sql(root/"orders.sqlite", """SELECT s.id,s.created,s.model,s.status,s.context,s.result,
          a.created,a.action,a.status,a.detail FROM management_shadow s
          LEFT JOIN management_attempts a ON a.proposal_id=s.id AND a.symbol=s.symbol
          WHERE s.symbol=? ORDER BY s.created,s.id""",(symbol,))
    return build(symbol,p,r,x,l,d,m)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="/var/lib/recover-trading/demo")
    p.add_argument("--learning-dir",default="/var/lib/recover-trading/outcome-learning")
    p.add_argument("--symbol",required=True,choices=SYMBOLS)
    a=p.parse_args()
    print(json.dumps(report(Path(a.data_dir)/a.symbol,a.symbol,a.learning_dir),allow_nan=False,indent=2))

if __name__=="__main__":main()
