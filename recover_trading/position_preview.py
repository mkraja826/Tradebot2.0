"""Position lifecycle observation and offline transition model.

No broker/provider imports, order payloads or execution integration.
"""
from dataclasses import dataclass,replace
from .performance import dec

VERSION="position-lifecycle-preview-v1"
MAX_AGE=180

def observe(snapshot,symbol,now,unknown_count=None):
    out={"version":VERSION,"symbol":symbol,"execution_effect":"none",
        "position_state":"unavailable","bracket_state":"unverified","observed":None,
        "size":None,"unresolved_submissions":unknown_count,"legs":[]}
    if not isinstance(snapshot,dict) or snapshot.get("symbol")!=symbol:
        return out
    observed=snapshot.get("observed")
    if type(observed) is not int or not 0<=now-observed<=MAX_AGE:
        out.update(position_state="stale_or_invalid",observed=observed)
        return out
    out["observed"]=observed
    errors=snapshot.get("errors") or {}
    positions=snapshot.get("positions")
    if not isinstance(positions,list) or "positions" in errors:return out
    orders=snapshot.get("active_orders")
    complete=snapshot.get("active_orders_complete") is True and isinstance(orders,list) and "active_orders" not in errors
    if not positions:
        out.update(position_state="flat",size="0",bracket_state="residual_orders_observed" if complete and orders else "no_orders_observed" if complete else "unverified")
        return out
    if len(positions)!=1 or not isinstance(positions[0],dict):
        out["position_state"]="ambiguous";return out
    p=positions[0];qty=dec(p.get("size"));pid=p.get("product_id")
    if qty is None or qty==0 or pid is None:return out
    out.update(position_state="long" if qty>0 else "short",size=str(qty),
        entry_price=p.get("entry_price"),mark_price=p.get("mark_price"))
    if not complete:return out
    expected="sell" if qty>0 else "buy"
    legs=[]
    for order in orders:
        if not isinstance(order,dict):continue
        if str(order.get("product_id"))!=str(pid) or order.get("state") not in ("open","pending"):continue
        kind=order.get("stop_order_type")
        if kind not in ("stop_loss_order","take_profit_order"):continue
        trigger=dec(order.get("stop_price"));remaining=dec(order.get("unfilled_size"))
        legs.append({"type":kind,"side":order.get("side"),"trigger":str(trigger) if trigger is not None else None,
            "remaining":str(remaining) if remaining is not None else None,
            "matching_quantity":remaining==abs(qty),"matching_side":order.get("side")==expected,
            "reduce_only":order.get("reduce_only") is True,"bracket_order":order.get("bracket_order") is True,
            "valid_trigger":trigger is not None and trigger>0})
    out["legs"]=legs
    types={leg["type"] for leg in legs}
    if len(legs)==2 and types=={"stop_loss_order","take_profit_order"} and all(
        all(leg[k] for k in ("matching_quantity","matching_side","reduce_only","bracket_order","valid_trigger")) for leg in legs):
        out["bracket_state"]="matching_legs_observed"
    else:out["bracket_state"]="incomplete_or_mismatched_legs"
    return out

@dataclass(frozen=True)
class Simulation:
    """Abstract contract-count state; fixture-only, never executable."""
    size:int=0
    phase:str="ready"
    pending:str|None=None
    before:int|None=None
    expected:int|None=None

def propose(state,action,*,side=None,quantity=None):
    if state.phase!="ready":raise ValueError("simulation awaiting reconciliation")
    if action=="maintain":
        if not state.size:raise ValueError("no position")
        return state
    if action=="open":
        if state.size or side not in ("long","short") or type(quantity) is not int or quantity<=0:raise ValueError("invalid simulated opening")
        expected=quantity if side=="long" else -quantity
    elif action=="update_bracket":
        if not state.size:raise ValueError("no position")
        expected=state.size
    elif action=="close":
        if not state.size or type(quantity) is not int or not 0<quantity<=abs(state.size):raise ValueError("invalid simulated close")
        expected=state.size-quantity if state.size>0 else state.size+quantity
    else:raise ValueError("unknown simulated action")
    return replace(state,phase="awaiting_observation",pending=action,before=state.size,expected=expected)

def reconcile(state,*,observed_size,terminal=False,bracket_verified=False):
    # A broker acknowledgment is not a terminal fill. Explicit terminal
    # evidence plus a new position observation are required for simulation.
    if state.phase!="awaiting_observation":raise ValueError("no pending simulation")
    if type(observed_size) is not int or not terminal:return state
    lo,hi=sorted((state.before,state.expected))
    if not lo<=observed_size<=hi:
        return replace(state,phase="unexpected_position",size=observed_size)
    if observed_size and not bracket_verified:
        return replace(state,phase="bracket_unverified",size=observed_size)
    return Simulation(size=observed_size)
