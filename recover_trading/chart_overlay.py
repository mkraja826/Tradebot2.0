"""Read-only chart annotations from observed demo fills and position snapshots."""
from .performance import dec,stamp
VERSION="chart-overlay-v1"
PRODUCTS={"BTCUSD":84,"XAUTUSD":181689}
def positive(x):
    n=dec(x)
    return float(n) if n is not None and n>0 else None

def build(symbol,snapshot,preview,cost,fills,management,now):
    pid=PRODUCTS[symbol];markers=[];seen=set()
    for f in fills or []:
        if not isinstance(f,dict):continue
        i=f.get("id");t=stamp(f);q=dec(f.get("size"));p=positive(f.get("price"));side=f.get("side")
        if not isinstance(i,str) or not i or i in seen or f.get("product_symbol")!=symbol or str(f.get("product_id"))!=str(pid) or t is None or not 0<t.timestamp()<=now+1 or q is None or q<=0 or p is None or side not in ("buy","sell"):continue
        seen.add(i);after=dec((f.get("new_position") or {}).get("size"));kind="fill"
        if after is not None:
            before=after-q*(1 if side=="buy" else -1)
            if before==0 and after!=0:kind="entry"
            elif before!=0 and after==0:kind="exit"
            elif before*after<0:kind="reversal"
            elif abs(after)<abs(before):kind="reduction"
            elif abs(after)>abs(before):kind="increase"
        markers.append({"id":i,"time":t.timestamp(),"price":p,"side":side,"size":str(q),"kind":kind})
    out={"version":VERSION,"symbol":symbol,"status":"position_unavailable","observed":preview.get("observed"),"lines":[],"fills":sorted(markers,key=lambda x:x["time"]),"execution_effect":"none"}
    latest=management.get("latest") or {}
    out["management"]={k:latest.get(k) for k in ("created","status","action")}
    observed=preview.get("observed")
    if not isinstance(snapshot,dict) or snapshot.get("symbol")!=symbol or preview.get("symbol")!=symbol or type(observed) is not int or not 0<=now-observed<=180 or snapshot.get("observed")!=observed:return out
    positions=snapshot.get("positions")
    if preview.get("position_state")=="flat" and positions==[]:
        out["status"]="flat";return out
    if not isinstance(positions,list) or len(positions)!=1:return out
    p=positions[0];q=dec(p.get("size"));e=positive(p.get("entry_price"));m=positive(p.get("mark_price"))
    if p.get("product_symbol")!=symbol or str(p.get("product_id"))!=str(pid) or q is None or not q or q!=dec(preview.get("size")) or e is None or m is None or preview.get("position_state")!=("long" if q>0 else "short"):return out
    out.update(status="position_observed",direction="LONG" if q>0 else "SHORT",contracts=str(abs(q)),entry_price=e,mark_price=m,bracket_state=preview.get("bracket_state"),
        unrealized_pnl=str(v) if (v:=dec(p.get("unrealized_pnl"))) is not None else None,
        lines=[{"kind":"entry","price":e},{"kind":"mark","price":m}])
    if preview.get("bracket_state")=="matching_legs_observed":
        for l in preview.get("legs",[]):
            k={"stop_loss_order":"stop","take_profit_order":"target"}.get(l.get("type"));price=positive(l.get("trigger"))
            if k and price is not None:out["lines"].append({"kind":k,"price":price})
    if cost.get("status")=="commission_only_estimate" and dec(cost.get("remaining_contracts"))==abs(q) and dec(cost.get("entry_price"))==dec(p.get("entry_price")) and cost.get("direction")==out["direction"]:
        price=positive(cost.get("break_even_exit_fill_price"))
        if price is not None:out["lines"].append({"kind":"break_even","price":price})
    return out
