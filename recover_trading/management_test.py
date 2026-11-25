"""Controlled offline management test protocol using archived demo shapes.

Read-only input journal; no broker, network, provider, or order mutation.
"""
import argparse,copy,json,sqlite3,time
from pathlib import Path
from contextlib import closing
from .performance import dec
from .position_preview import observe,Simulation,propose,reconcile
from .management_compat import close_evidence,amendment_response

VERSION="management-test-v1"

def baseline(snapshot,symbol,receipts,now):
    view=observe(snapshot,symbol,now)
    if view["bracket_state"]!="matching_legs_observed":
        return {"status":"baseline_unavailable","position_state":view["position_state"]}
    p=snapshot["positions"][0];pid=p["product_id"];q=dec(p["size"])
    legs={o["stop_order_type"]:o for o in snapshot["active_orders"]
          if str(o.get("product_id"))==str(pid) and o.get("state") in ("pending","open") and o.get("stop_order_type") in ("stop_loss_order","take_profit_order")}
    ids=[o.get("id") for o in legs.values()]
    if any(x is None or isinstance(x,bool) or not str(x) for x in ids) or len(set(map(str,ids)))!=2:
        return {"status":"leg_identity_unverified","position_state":view["position_state"]}
    candidates=[]
    for r in receipts:
        if (r.get("id") is not None and str(r.get("product_id"))==str(pid)
            and r.get("side")==("buy" if q>0 else "sell") and r.get("state")=="closed"
            and dec(r.get("size"))==abs(q) and dec(r.get("unfilled_size"))==0
            and dec(r.get("bracket_stop_loss_price"))==dec(legs["stop_loss_order"]["stop_price"])
            and dec(r.get("bracket_take_profit_price"))==dec(legs["take_profit_order"]["stop_price"])
            and str(r["id"]) not in set(map(str,ids))):
            candidates.append(r)
    return {"status":"matching_distinct_leg_ids","position_state":view["position_state"],
        "size":str(q),"leg_ids_distinct":True,"matching_entry_receipts":len(candidates),
        "amendment_target":"unverified","receipt_match_is_not_parent_link":True}

def scenarios(snapshot,symbol,receipts,now):
    b=baseline(snapshot,symbol,receipts,now)
    if b["status"]!="matching_distinct_leg_ids":return b,[]
    q=dec(b["size"])
    if q!=q.to_integral_value() or abs(q)<2:return b,[]
    qty=int(q);sign=1 if qty>0 else -1
    pid=snapshot["positions"][0]["product_id"];reduction=abs(qty)//2;remaining=qty-sign*reduction
    side="sell" if qty>0 else "buy"
    # Synthetic IDs only, not the IDs of actual orders.
    order={"id":"fixture-close","product_id":pid,"side":side,"size":abs(qty),
           "unfilled_size":abs(qty)-reduction,"reduce_only":True,"state":"cancelled"}
    fill={"id":"fixture-fill","order_id":"fixture-close","product_id":pid,"side":side,"size":reduction}
    after=copy.deepcopy(snapshot);after["positions"][0]["size"]=remaining
    adjusted=copy.deepcopy(after)
    for leg in adjusted["active_orders"]:
        if leg.get("stop_order_type") in ("stop_loss_order","take_profit_order") and str(leg.get("product_id"))==str(pid):
            leg["size"]=leg["unfilled_size"]=abs(remaining)
    closed=copy.deepcopy(snapshot);closed["positions"]=[];closed["active_orders"]=[]
    residual=copy.deepcopy(closed);residual["active_orders"]=snapshot["active_orders"]
    pending=propose(Simulation(qty),"close",quantity=abs(qty))
    full_order={**order,"state":"closed","unfilled_size":0}
    full_fill={**fill,"size":abs(qty)}
    checks=[
        ("partial_fill_terminal",close_evidence(qty,remaining,order,[fill],pid),"partial_close_observed"),
        ("partial_stale_brackets",observe(after,symbol,now)["bracket_state"],"incomplete_or_mismatched_legs"),
        ("partial_resized_brackets",observe(adjusted,symbol,now)["bracket_state"],"matching_legs_observed"),
        ("full_fill_terminal",close_evidence(qty,0,full_order,[full_fill],pid),"full_close_observed"),
        ("full_close_no_residual",observe(closed,symbol,now)["bracket_state"],"no_orders_observed"),
        ("full_close_residual",observe(residual,symbol,now)["bracket_state"],"residual_orders_observed"),
        ("ack_without_terminal",reconcile(pending,observed_size=0).phase,"awaiting_observation"),
        ("amendment_success_only",amendment_response({"success":True}),"acknowledged_unverified"),
        ("duplicate_fill",close_evidence(qty,remaining,order,[fill,fill],pid),"fill_identity_unverified"),
        ("unexpected_position_change",close_evidence(qty,0,order,[fill],pid),"position_change_unverified")]
    return b,[{"scenario":name,"observed":got,"expected":expected,"passed":got==expected} for name,got,expected in checks]

def run(root,symbol,now):
    path=Path(root)/symbol/"orders.sqlite"
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        db.execute("BEGIN")
        row=db.execute("SELECT detail FROM lifecycle_snapshots WHERE symbol=? ORDER BY id DESC LIMIT 1",(symbol,)).fetchone()
        receipts=[json.loads(r) for r, in db.execute("SELECT detail FROM orders WHERE symbol=? AND status='acknowledged'",(symbol,))]
    b,checks=scenarios(json.loads(row[0]) if row else None,symbol,receipts,now)
    return {"version":VERSION,"symbol":symbol,"baseline":b,"scenarios":checks,"passed":sum(x["passed"] for x in checks),
            "scenario_count":len(checks),"exchange_mutations":0,"actual_demo_management_test":"not_performed",
            "execution_effect":"none"}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--data-dir",required=True);a=p.parse_args()
    failed=False
    for symbol in ("BTCUSD","XAUTUSD"):
        r=run(a.data_dir,symbol,int(time.time()));print(json.dumps(r,allow_nan=False),flush=True)
        failed=failed or r["scenario_count"]==0 or r["passed"]!=r["scenario_count"]
    return int(failed)
if __name__=="__main__":raise SystemExit(main())
