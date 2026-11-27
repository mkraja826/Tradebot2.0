"""Gold V2 resizing contract research. No order submission or amendments."""
from decimal import Decimal
from .gold_v2_episode import d
from .position_preview import observe
from .management_executor import identity

VERSION="gold-v2-resize.1"
SYMBOL="XAUTUSD"

def addition_preview(snapshot,product,*,now,initial_qty,initial_entry,initial_stop,atr,
                     completed_close,quote,adds,previous_reduction,cost_bps=15):
    def out(s,**kw):return {"version":VERSION,"symbol":SYMBOL,"status":s,"execution_effect":"none",**kw}
    v=observe(snapshot,SYMBOL,now)
    if v["bracket_state"]!="matching_legs_observed" or len(snapshot.get("active_orders",[]))!=2:
        return out("bracket_unverified")
    if any(o.get("stop_trigger_method")!="mark_price" for o in snapshot["active_orders"]):
        return out("trigger_unverified")
    if product.get("symbol")!=SYMBOL or product.get("id")!=snapshot["positions"][0].get("product_id"):
        raise ValueError("wrong_product")
    if type(adds) is not int or not 0<=adds<=5 or type(previous_reduction) is not bool:
        raise ValueError("invalid_episode_state")
    if adds==5 or previous_reduction:return out("no_addition_hypothesis")
    q=d(v["size"]);side=1 if q>0 else -1
    n,base,sl0,a,close,fees=map(d,(initial_qty,initial_entry,initial_stop,atr,completed_close,cost_bps))
    avg,mark=d(v["entry_price"]),d(v["mark_price"])
    if min(n,base,sl0,a,close,avg,mark)<=0 or n!=int(n) or abs(q)!=n*(adds+1) or not 0<=fees<10000:
        return out("quantity_or_input_unverified")
    if side*(base-sl0)<=0:return out("initial_risk_unverified")
    legs={l["type"]:d(l["trigger"]) for l in v["legs"]}
    sl,tp=legs["stop_loss_order"],legs["take_profit_order"]
    if side*(sl-sl0)<0 or not (sl<mark<tp if side==1 else tp<mark<sl):
        return out("current_bracket_incompatible")
    if side*(close-base)<Decimal(".5")*a*(adds+1):
        return out("threshold_not_reached")
    if quote.get("status")!="fresh_book":return out("quote_unavailable")
    stamp=quote.get("timestamp_us")
    if type(stamp) is not int or not 0<=now*1000000-stamp<=30000000:
        return out("quote_stale")
    bid,ask=d(quote["best_bid"]),d(quote["best_ask"])
    if not 0<bid<=ask:return out("quote_unavailable")
    px=ask if side==1 else bid
    if side*(px-base)<=0 or not (sl<px<tp if side==1 else tp<px<sl):
        return out("addition_price_incompatible")
    fee=fees/20000
    # All quantities are contracts. Contract value cancels from comparison.
    # Current weighted entry is sufficient only before any reductions.
    risk=n*(abs(base-sl0)+fee*(base+sl0))
    net=side*(abs(q)*(sl-avg)+n*(sl-px))-fee*(abs(q)*(avg+sl)+n*(px+sl))
    if net < -risk:return out("modeled_stop_budget_exceeded")
    new_qty=abs(q)+n
    weighted=(abs(q)*avg+n*px)/new_qty
    return out("addition_preview",side="buy" if side==1 else "sell",
               additional_contracts=int(n),expected_signed_size=int(side*new_qty),
               expected_weighted_entry=str(weighted),expected_stop=str(sl),expected_target=str(tp),
               before_identity=identity(snapshot),modeled_stop_pnl_contract_price_units=str(net),
               initial_risk_contract_price_units=str(risk),requires_verified_atomic_bracket_coverage=True,
               dispatch_supported=False)

def verify_addition(before,after,product,order,fills,*,now,expected_client_id,requested_contracts,complete):
    """Verify an already-observed addition; not an execution authorization.

    Assumes trusted before snapshot, dedicated account, complete order/fill
    evidence and an independently reserved expected client ID.
    """
    def out(s,**kw):return {"version":VERSION,"symbol":SYMBOL,"status":s,"execution_effect":"none",**kw}
    if complete is not True:return out("incomplete_fills")
    if type(requested_contracts) is not int or requested_contracts<=0:return out("invalid_requested_size")
    try:
        v=observe(before,SYMBOL,before["observed"])
        w=observe(after,SYMBOL,now)
        if any(x["bracket_state"]!="matching_legs_observed" for x in (v,w)):
            return out("bracket_coverage_unverified")
        if not before["observed"]<after["observed"]<=now:return out("snapshot_order_unverified")
        if any(len(s["active_orders"])!=2 or any(o.get("stop_trigger_method")!="mark_price" for o in s["active_orders"]) for s in (before,after)):
            return out("bracket_trigger_unverified")
        p0,p1=before["positions"][0],after["positions"][0]
        pid=product.get("id")
        if product.get("symbol")!=SYMBOL or pid!=p0.get("product_id") or pid!=p1.get("product_id"):
            return out("product_mismatch")
        if identity(before) is None or identity(after) is None or p0["created_at"]!=p1["created_at"]:
            return out("position_lineage_changed")
        q0,q1=d(v["size"]),d(w["size"]);side=1 if q0>0 else -1
        if (order.get("client_order_id")!=expected_client_id or order.get("id") is None
            or order.get("product_id")!=pid or order.get("side")!=("buy" if side==1 else "sell")
            or order.get("reduce_only") is not False or order.get("state") not in ("closed","cancelled","canceled")
            or d(order["size"])!=requested_contracts):
            return out("order_identity_unverified")
        remaining=d(order["unfilled_size"])
        if not 0<=remaining<=requested_contracts or (order["state"]=="closed" and remaining):
            return out("order_quantity_unverified")
        filled=Decimal(requested_contracts)-remaining
        if filled<=0:return out("no_addition_fill")
        matched=[];seen=set()
        from .gold_v2_episode import timestamp
        for f in fills:
            t=timestamp(f["created_at"])
            if t<=before["observed"] or t>after["observed"]:return out("fill_time_unverified")
            if str(f.get("order_id"))!=str(order["id"]) or f.get("product_id")!=pid or f.get("side")!=order["side"]:
                return out("unattributed_fill")
            fid=str(f.get("id"))
            if f.get("id") is None or fid in seen:return out("duplicate_fill")
            seen.add(fid);matched.append((t,f))
        matched.sort(key=lambda x:x[0])
        if any(a[0]==b[0] for a,b in zip(matched,matched[1:])):return out("ambiguous_fill_order")
        total=weighted=Decimal(0)
        for _,f in matched:
            q,p=d(f["size"]),d(f["price"])
            if q<=0 or q!=int(q) or p<=0:return out("invalid_fill")
            total+=q;weighted+=q*p
            if d(f["new_position"]["size"])!=q0+side*total:return out("fill_chain_mismatch")
        if total!=filled or q1!=q0+side*total:return out("quantity_mismatch")
        if weighted/total!=d(order["average_fill_price"]):return out("receipt_price_mismatch")
        expected=(abs(q0)*d(v["entry_price"])+weighted)/abs(q1)
        if expected!=d(w["entry_price"]):return out("weighted_entry_mismatch")
        l0={l["type"]:d(l["trigger"]) for l in v["legs"]}
        l1={l["type"]:d(l["trigger"]) for l in w["legs"]}
        if side*(l1["stop_loss_order"]-l0["stop_loss_order"])<0:return out("stop_loosened")
        if l1["take_profit_order"]!=l0["take_profit_order"]:return out("target_changed")
        mark=d(w["mark_price"])
        if not (l1["stop_loss_order"]<mark<l1["take_profit_order"] if side==1 else l1["take_profit_order"]<mark<l1["stop_loss_order"]):
            return out("crossed_bracket")
        return out("addition_observed",filled_contracts=int(total),signed_size=int(q1),
                   weighted_entry=str(expected),bracket_coverage="matching_legs_observed",
                   continuous_coverage_verified=False)
    except (KeyError,ValueError,TypeError,ArithmeticError,AttributeError):
        return out("invalid_evidence")
