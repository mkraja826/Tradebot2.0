"""Synthetic management handoff only; no broker or provider transport."""
from tradebot.management_instructions_v3 import prepare,validate
from tradebot.position_observer_v3 import number
from tradebot.opportunity_journal_v3 import digest

def fixture_position(o,s,now):
    if o.get("fixture_only") is not True or o.get("symbol")!=s or o.get("halted") is not False:
        raise ValueError("fixture_scope_required")
    if type(o.get("observed_us")) is not int or not 0<=now-o["observed_us"]/1e6<=60:
        raise ValueError("stale_position")
    if o.get("status")!="open_protection_reported" or o.get("open_order_count")!=2 or len(o.get("positions",[]))!=1:
        raise ValueError("protected_position_required")
    p=o["positions"][0]
    if not isinstance(p.get("fixture_position_id"),str) or not p["fixture_position_id"]:raise ValueError("missing_fixture_identity")
    qty,mark,sl,tp=(number(p[k],True) for k in ("quantity","mark","stop_loss","take_profit"))
    if qty!=qty.to_integral_value() or p.get("protection")!="broker_reported_bracket":raise ValueError("invalid_fixture_inventory")
    if p["side"] not in ("LONG","SHORT") or not (sl<mark<tp if p["side"]=="LONG" else tp<mark<sl):raise ValueError("invalid_current_bracket")
    return p

def adapt(req,response,current,*,now):
    s=req["payload"]["symbol"];old=req["payload"]["observation"]
    p=fixture_position(old,s,now);q=fixture_position(current,s,now)
    # Recheck the exact context before preparing any hypothetical instruction.
    if digest(old)!=digest(current):raise ValueError("position_context_changed")
    spec=req["payload"]["product"]
    if prepare(old,spec,now=now)!=req:raise ValueError("invalid_request")
    validated=validate(req,response)
    action=response["action"];v=response["value"];qty=int(number(p["quantity"],True))
    remaining=qty;sl=p["stop_loss"];tp=p["take_profit"]
    if action in ("MOVE_STOP","BREAKEVEN_STOP"):sl=str(number(v,True))
    elif action=="MOVE_TARGET":tp=str(number(v,True))
    elif action=="PARTIAL_EXIT":remaining-=v
    elif action=="CLOSE":remaining=0
    return dict(mode="synthetic_management_handoff",symbol=s,action=action,
                instruction_id=validated["instruction_id"],context_id=req["context_id"],
                fixture_position_id=p["fixture_position_id"],side=p["side"],
                original_quantity=qty,expected_remaining=remaining,
                expected_stop=sl if remaining else None,expected_target=tp if remaining else None,
                context_observed_us=old["observed_us"],execution_authorized=False,
                orders_submitted=0,scanner_control=False,broker_verified=False)

def observe(plan,after,*,now):
    out=dict(status="unknown_requires_reconciliation",broker_verified=False,settlement_verified=False,execution_authorized=False,retry_authorized=False)
    if plan.get("mode")!="synthetic_management_handoff" or plan.get("execution_authorized") is not False:raise ValueError("fixture_only")
    if not isinstance(after,dict) or after.get("fixture_only") is not True or after.get("symbol")!=plan["symbol"]:return out
    t=after.get("observed_us")
    if type(t) is not int or t<=plan["context_observed_us"] or not 0<=now-t/1e6<=60:return out
    if plan["expected_remaining"]==0:
        if after.get("status")=="flat_observed" and after.get("positions")==[] and after.get("open_order_count")==0:
            out["status"]="fixture_flat_observed_unsettled"
        return out
    try:
        p=fixture_position(after,plan["symbol"],now)
        if p["fixture_position_id"]==plan["fixture_position_id"] and p["side"]==plan["side"] and number(p["quantity"])==plan["expected_remaining"] and number(p["stop_loss"])==number(plan["expected_stop"]) and number(p["take_profit"])==number(plan["expected_target"]):
            out["status"]="fixture_expected_state_observed"
    except (ValueError,TypeError,KeyError):pass
    return out
