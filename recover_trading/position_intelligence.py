"""Read-only position management outcome diagnostics, not an exit policy."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from .performance import dec, stamp, read_performance
from .trade_excursion import report as excursions
from .trade_intelligence import sql, obj, mapping, episode_key, unique_match, money

VERSION="position-intelligence-v1"
SYMBOLS=("BTCUSD","XAUTUSD")

def episode_fills(ep, fills, pid, currency):
    start=stamp({"created_at":ep.get("opened")})
    end=stamp({"created_at":ep.get("closed")})
    if not start or not end or start>=end:return None
    rows=sorted([(t,f) for f in fills if (t:=stamp(f)) is not None and start<=t<=end],key=lambda x:x[0])
    if len(rows)!=ep.get("fills") or len(rows)<2 or rows[0][0]!=start or rows[-1][0]!=end:return None
    if len({t for t,f in rows})!=len(rows) or any(f.get("id") is None for t,f in rows) or len({str(f["id"]) for t,f in rows})!=len(rows):return None
    sign=1 if ep.get("direction")=="LONG" else -1 if ep.get("direction")=="SHORT" else 0
    if not sign:return None
    prev=0;entry=None;exits=[]
    for i,(t,f) in enumerate(rows):
        q,p,fee=map(dec,(f.get("size"),f.get("price"),f.get("commission")))
        after=dec(mapping(f.get("new_position")).get("size"))
        side=1 if f.get("side")=="buy" else -1 if f.get("side")=="sell" else 0
        if None in (q,p,fee,after) or min(q,p)<=0 or not side or after!=prev+side*q or str(f.get("product_id"))!=str(pid) or f.get("settling_asset_symbol")!=currency:return None
        if i==0:
            if side!=sign:return None
            entry=f
        else:
            if side==sign or abs(after)>=abs(prev) or after*sign<0:return None
            exits.append(f)
        prev=after
    if prev!=0:return None
    return entry,exits

def reduction_evidence(ep, fills, records, spec):
    """Match journal-verified reduction receipts to actual fills; no counterfactual."""
    pid=spec.get("id");currency=mapping(spec.get("settling_asset")).get("symbol")
    cv=dec(spec.get("contract_value"))
    if pid is None or not currency or currency!=mapping(spec.get("quoting_asset")).get("symbol") or spec.get("notional_type")!="vanilla" or cv is None or cv<=0:return {"status":"unsupported_product","actions":[]}
    path=episode_fills(ep,fills,pid,currency)
    if path is None:return {"status":"unverified_or_multi_entry_episode","actions":[]}
    entry,exits=path;en=dec(entry["price"]);entry_qty=dec(entry["size"]);entry_fee=dec(entry["commission"])
    start=stamp(entry);end=stamp({"created_at":ep["closed"]})
    gross=sum((dec(f["price"])-en)*dec(f["size"])*cv*(1 if ep["direction"]=="LONG" else -1) for f in exits)
    fees=entry_fee+sum(dec(f["commission"]) for f in exits)
    if abs(gross-(dec(ep.get("gross_pnl")) or 0))>dec("0.000001") or abs(fees-(dec(ep.get("fees")) or 0))>dec("0.000001") or dec(ep.get("gross_pnl")) is None or dec(ep.get("fees")) is None:
        return {"status":"episode_accounting_mismatch","actions":[]}
    candidates=[]
    for ident,model,created,status,raw_c,raw_r,attempt_at,action,attempt_status,raw_a in records or []:
        if type(created) is not int or type(attempt_at) is not int or not start.timestamp()<created<=attempt_at<=end.timestamp():continue
        if status!="proposed" or attempt_status!="verified" or action not in ("reduce","close"):continue
        c=obj(raw_c);p=mapping(obj(raw_r).get("proposal"));a=obj(raw_a);receipt=mapping(a.get("receipt"));plan=mapping(a.get("plan"));ev=mapping(a.get("evidence"))
        identity=c.get("execution_identity")
        cid=hashlib.sha256(("management:"+ident).encode()).hexdigest()[:32]
        if (not identity or identity!=a.get("identity") or a.get("client_id")!=cid or receipt.get("client_order_id")!=cid
            or receipt.get("id") is None or str(receipt.get("product_id"))!=str(pid) or receipt.get("reduce_only") is not True
            or p.get("action")!=action or plan.get("action")!=action or str(plan.get("product_id"))!=str(pid)
            or ev.get("target_size_observed") is not True or ev.get("status") not in ("partial_close_observed","full_close_observed")):continue
        matched=[f for f in exits if str(f.get("order_id"))==str(receipt["id"])]
        requested=dec(plan.get("requested_reduction"))
        if not matched or requested is None or sum(dec(f["size"]) for f in matched)!=requested:continue
        if any(stamp(f).timestamp()<attempt_at for f in matched):continue
        qty=sum(dec(f["size"]) for f in matched)
        realized=sum((dec(f["price"])-en)*dec(f["size"])*cv*(1 if ep["direction"]=="LONG" else -1) for f in matched)
        exit_fee=sum(dec(f["commission"]) for f in matched)
        allocated=entry_fee*qty/entry_qty
        candidates.append({"proposal_id":ident,"model":model,"action":action,"receipt_order_id":str(receipt["id"]),
            "matched_fill_ids":[str(f["id"]) for f in matched],"closed_contracts":money(qty),
            "gross_contribution":money(realized),"exit_fees":money(exit_fee),"prorated_entry_fees":money(allocated),
            "net_contribution_before_funding":money(realized-exit_fee-allocated),
            "basis":"observed_fill_contribution_not_incremental_management_benefit"})
    counts=Counter(i for row in candidates for i in row["matched_fill_ids"])
    valid=[r for r in candidates if all(counts[i]==1 for i in r["matched_fill_ids"])]
    return {"status":"observed" if records is not None else "management_journal_unavailable",
            "actions":valid,"ambiguous_action_count":len(candidates)-len(valid),
            "total_exit_fills":len(exits),"matched_exit_fills":sum(len(r["matched_fill_ids"]) for r in valid),
            "episode_fee_total":money(fees)}

def retention(ep,x):
    mfe=dec(x.get("mfe_bps"));mae=dec(x.get("mae_bps"));exit_return=dec(x.get("gross_weighted_exit_return_bps"));net=dec(ep.get("net_before_funding"))
    out={"status":"insufficient_or_flagged_excursion","observed_favorable_bps":money(mfe),"observed_adverse_bps":money(mae),
         "weighted_exit_bps":money(exit_return),"observed_gap_bps":None,"capture_upper_bound_pct":None,"diagnostic":None}
    if x.get("status")!="complete_interior_lower_bound" or None in (mfe,mae,exit_return,net) or min(mfe,mae)<0 or max(mfe,mae)>=1000:return out
    out.update(status="descriptive_lower_bound",observed_gap_bps=money(max(0,mfe-exit_return)),
        capture_upper_bound_pct=money(exit_return/mfe*100) if mfe>0 and exit_return>0 else None,
        diagnostic="little_observed_favorable_movement" if net<0 and mfe<10 else
        "favorable_movement_then_net_loss" if net<0 and mfe>=25 else "other_observed_outcome")
    return out

def report(root,symbol):
    if symbol not in SYMBOLS:raise ValueError("unsupported symbol")
    root=Path(root);p=read_performance(root,symbol);x=excursions(root,symbol,p)
    d=sql(root/"decisions.sqlite","SELECT id,context FROM decisions WHERE symbol=?",(symbol,))
    f=sql(root/"orders.sqlite","SELECT detail FROM observed_fills WHERE symbol=?",(symbol,))
    m=sql(root/"orders.sqlite","""SELECT s.id,s.model,s.created,s.status,s.context,s.result,a.created,a.action,a.status,a.detail
        FROM management_shadow s LEFT JOIN management_attempts a ON a.proposal_id=s.id AND a.symbol=s.symbol
        WHERE s.symbol=?""",(symbol,))
    rows=[]
    for e in p.get("recent_episodes",[]):
        if e.get("attribution")!="single_recover_entry_order":continue
        rec=unique_match(d or [],lambda r:r[0]==e.get("decision_id"))
        spec=mapping(mapping(obj(rec[1]).get("demo_account")).get("product")) if rec else {}
        ex=unique_match(x.get("episodes",[]),lambda r:episode_key(r)==episode_key(e)) or {}
        r=reduction_evidence(e,[obj(v[0]) for v in f or []],m,spec) if f is not None else {"status":"fill_journal_unavailable","actions":[]}
        rows.append({"decision_id":e.get("decision_id"),"closed":e.get("closed"),"net_before_funding":e.get("net_before_funding"),
                     "retention":retention(e,ex),"management_fill_evidence":r})
    expected=mapping(p.get("recover_attributed")).get("closed_episodes")
    return {"version":VERSION,"symbol":symbol,"status":p.get("status"),"execution_effect":"none",
        "coverage":{"expected_attributed_episodes":expected,"reported":len(rows),"complete_window":type(expected) is int and expected==len(rows),
                    "management_journal_available":m is not None},
        "retention_counts":dict(Counter(r["retention"]["diagnostic"] or r["retention"]["status"] for r in rows)),
        "matched_management_actions":sum(len(r["management_fill_evidence"]["actions"]) for r in rows),
        "trades":rows,"limitations":["Actual receipt-linked fill contribution is not incremental benefit versus holding or another exit.",
        "Single opening fill only; missing receipts, timestamp ambiguity or identity mismatch remain unmatched.",
        "Observed trade-price excursions exclude boundary candles, are lower bounds and are not executable peak profits.",
        "1000/25/10 bps flags are descriptive research categories, not execution thresholds.",
        "No replay, profit forecast, live policy change, AI call or order request. Funding and AI costs excluded."]}

def main():
    p=argparse.ArgumentParser();p.add_argument("--data-dir",default="/var/lib/recover-trading/demo")
    p.add_argument("--symbol",required=True,choices=SYMBOLS);a=p.parse_args()
    print(json.dumps(report(Path(a.data_dir)/a.symbol,a.symbol),allow_nan=False,indent=2))
if __name__=="__main__":main()
