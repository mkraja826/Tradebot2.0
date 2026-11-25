"""Read-only filled-entry bracket diagnostics; never changes exchange orders."""
from .performance import dec
from .position_preview import observe

VERSION="postfill-bracket-v1"

def audit(snapshot,symbol,now,receipts,fills):
    view=observe(snapshot,symbol,now)
    out={"version":VERSION,"symbol":symbol,"execution_effect":"none",
         "position_state":view["position_state"],"bracket_state":view["bracket_state"],
         "observed":view["observed"],"size":view["size"],"entry_evidence":None,
         "status":"unverified"}
    if view["position_state"]=="flat":
        out["status"]="flat";return out
    if view["position_state"] not in ("long","short"):return out
    out["status"]="matching_legs_observed" if view["bracket_state"]=="matching_legs_observed" else "bracket_evidence_missing_or_mismatched"
    p=snapshot["positions"][0]
    pid=p["product_id"];qty=dec(p["size"]);entry=dec(p.get("entry_price"))
    candidates=[]
    for r in receipts:
        if not isinstance(r,dict) or r.get("id") is None or str(r.get("product_id"))!=str(pid):continue
        if r.get("state")!="closed" or dec(r.get("unfilled_size"))!=0 or dec(r.get("size"))!=abs(qty):continue
        side="buy" if qty>0 else "sell"
        if r.get("side")!=side:continue
        matched=[f for f in fills if str(f.get("order_id"))==str(r["id"]) and str(f.get("product_id"))==str(pid)]
        if not matched or any(f.get("side")!=side or f.get("id") is None or dec(f.get("size")) is None or dec(f["size"])<=0 or dec(f.get("price")) is None or dec(f["price"])<=0 for f in matched):continue
        if len({str(f["id"]) for f in matched})!=len(matched):continue
        total=sum(dec(f["size"]) for f in matched)
        if total!=abs(qty):continue
        price=sum(dec(f["size"])*dec(f["price"]) for f in matched)/total
        if entry is None or entry!=price:continue
        candidates.append((r,price))
    if len(candidates)!=1:return out
    r,price=candidates[0]
    sl,tp=dec(r.get("bracket_stop_loss_price")),dec(r.get("bracket_take_profit_price"))
    geometry=None
    if sl is not None and tp is not None and sl>0 and tp>0:
        geometry=sl<price<tp if qty>0 else tp<price<sl
    out["entry_evidence"]={"fill_price":str(price),"receipt_stop":str(sl) if sl is not None else None,
        "receipt_target":str(tp) if tp is not None else None,"bracket_price_geometry":geometry,
        "attribution":"unique_quantity_and_entry_price_match_not_proven_position_lineage"}
    return out
