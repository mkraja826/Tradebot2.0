"""Offline TP-only amendment contract. No broker, provider or execution integration."""
from .performance import dec
from .position_preview import observe
from .bracket_contract import fixture_payload,verify_fixture
VERSION="target-amendment-preview-v1"

def inspect(snapshot,symbol,now):
    out={"version":VERSION,"status":"position_or_bracket_unverified","execution_effect":"none","exchange_mutation_verified":False}
    v=observe(snapshot,symbol,now)
    if v["bracket_state"]!="matching_legs_observed":return out
    p=snapshot["positions"][0];orders=snapshot["active_orders"]
    if len(orders)!=2 or not isinstance(p.get("created_at"),str) or not p["created_at"]:return out
    if any(not isinstance(r,dict) or type(r.get("id")) is not int or r["id"]<=0 or r.get("state")!="pending" or r.get("stop_trigger_method")!="mark_price" for r in orders):return out
    if len({r["id"] for r in orders})!=2:return out
    legs={r["stop_order_type"]:r for r in orders}
    q,m,e=map(dec,(v["size"],v.get("mark_price"),v.get("entry_price")))
    sl,tp=(dec(legs[k]["stop_price"]) for k in ("stop_loss_order","take_profit_order"))
    if any(x is None for x in (q,m,e,sl,tp)) or not q or q!=q.to_integral_value() or min(m,e,sl,tp)<=0:return out
    if not (sl<m<tp if q>0 else tp<m<sl):return out
    pid=p.get("product_id")
    if type(pid) is not int or pid<=0:return out
    out.update(status="candidate_legs_observed",product_id=pid,position_created_at=p["created_at"],position_size=int(q),entry_price=str(e),mark_price=str(m),
        stop_order_id=legs["stop_loss_order"]["id"],target_order_id=legs["take_profit_order"]["id"],stop_price=str(sl),target_price=str(tp))
    return out

def plan(snapshot,symbol,now,product,target):
    """Explicit proposed target only; no generated price or exchange request."""
    v=inspect(snapshot,symbol,now)
    if v["status"]!="candidate_legs_observed":raise ValueError("candidate_unverified")
    if product.get("symbol")!=symbol or product.get("id")!=v["product_id"]:raise ValueError("product_identity")
    t=dec(target)
    if t is None or t==dec(v["target_price"]):raise ValueError("unchanged_or_invalid_target")
    fixture_payload(v["product_id"],v["position_size"],v["mark_price"],v["stop_price"],t,product.get("tick_size"))
    return {"version":VERSION,"symbol":symbol,"before":v,"desired_target":str(t),"method":"PUT","path":"/v2/orders",
        "payload":{"id":v["target_order_id"],"product_id":v["product_id"],"size":abs(v["position_size"]),"stop_price":format(t,"f")},
        "execution_effect":"none","mode":"offline_contract_only"}

def verify(p,snapshot,now):
    """Verify both unchanged SL and amended TP against a separate observation."""
    before=p["before"];v=inspect(snapshot,p["symbol"],now)
    if v["status"]!="candidate_legs_observed":return "observation_unverified"
    for k in ("product_id","position_created_at","position_size","entry_price","stop_order_id","target_order_id"):
        if v[k]!=before[k]:return "position_or_order_identity_changed"
    if dec(v["stop_price"])!=dec(before["stop_price"]):return "stop_changed"
    if dec(v["target_price"])!=dec(p["desired_target"]):return "target_mismatch"
    if verify_fixture(snapshot,p["symbol"],now,before["position_size"],before["stop_price"],p["desired_target"])!="matching_triggers_observed":return "legs_unverified"
    return "matching_target_and_unchanged_stop_observed"
