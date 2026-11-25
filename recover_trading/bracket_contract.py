"""Offline position-level bracket contract checks; no network calls."""
from .performance import dec
from .position_preview import observe

VERSION="position-bracket-contract-v1"

def repair_status(snapshot,symbol,now):
    view=observe(snapshot,symbol,now)
    out={"version":VERSION,"symbol":symbol,"position_state":view["position_state"],
         "status":"unverified","execution_effect":"none"}
    if view["position_state"]=="flat":
        out["status"]="no_position";return out
    if view["position_state"] not in ("long","short"):return out
    if view["bracket_state"]=="matching_legs_observed":
        out["status"]="existing_bracket_observed";return out
    if snapshot.get("active_orders_complete") is not True or not isinstance(snapshot.get("active_orders"),list) or "active_orders" in (snapshot.get("errors") or {}):
        return out
    out["status"]="existing_orders_require_review" if snapshot["active_orders"] else "position_without_active_orders"
    return out

def fixture_payload(product_id,position_size,mark,stop,target,tick):
    """Validate explicitly supplied fixture prices; never choose or send them."""
    if type(product_id) is not int or product_id<=0:raise ValueError("invalid product")
    q,m,s,t,k=map(dec,(position_size,mark,stop,target,tick))
    if any(x is None for x in (q,m,s,t,k)) or not q or min(m,s,t,k)<=0:
        raise ValueError("invalid inputs")
    if s%k or t%k:raise ValueError("unaligned trigger")
    if not (s<m<t if q>0 else t<m<s):raise ValueError("crossed trigger")
    return {"product_id":product_id,"stop_loss_order":{"order_type":"market_order","stop_price":format(s,"f")},
        "take_profit_order":{"order_type":"market_order","stop_price":format(t,"f")},
        "bracket_stop_trigger_method":"mark_price"}

def verify_fixture(snapshot,symbol,now,expected_size,stop,target):
    """Check observed quantity and trigger values, not merely HTTP success."""
    v=observe(snapshot,symbol,now)
    if dec(v.get("size"))!=dec(expected_size):return "position_changed"
    if v["bracket_state"]!="matching_legs_observed":return "legs_unverified"
    prices={x["type"]:dec(x["trigger"]) for x in v["legs"]}
    return "matching_triggers_observed" if prices=={"stop_loss_order":dec(stop),"take_profit_order":dec(target)} else "triggers_mismatch"
