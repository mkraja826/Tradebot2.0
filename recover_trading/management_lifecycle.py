"""Pure management lifecycle adapter. No broker mutations."""
from .management_shadow import validate,VERSION as SHADOW_VERSION
from .position_preview import observe
from .management_compat import close_evidence,amendment_response
from .bracket_contract import verify_fixture
from .performance import dec
VERSION="management-lifecycle-v1"

def plan(context,raw):
    if context.get("version") not in (SHADOW_VERSION,"management-shadow-v1","management-shadow-v2"):raise ValueError("context_version")
    proposal=validate(raw,context)
    p=context["position"];q=p["size"];pid=context["product"]["id"]
    if type(q) is not int or not q or type(pid) is not int or pid<=0:raise ValueError("position_identity")
    if p.get("direction")!=("long" if q>0 else "short"):raise ValueError("position_direction")
    action=proposal["action"]
    reduction=abs(q) if action=="close" else proposal.get("contracts",0)
    target=q-(reduction if q>0 else -reduction)
    out={"version":VERSION,"symbol":context["symbol"],"action":action,
        "product_id":pid,"before_size":q,"expected_size":target,
        "entry_price":p["entry_price"],"position_observed":context["position_observed"],
        "as_of":context["as_of"],"original_bracket_state":p["bracket_state"],
        "requested_reduction":reduction,"execution_effect":"none","mode":"simulation_only"}
    if action in ("repair_bracket","update_bracket"):
        out["desired_triggers"]={"stop_loss":proposal["stop_loss"],"take_profit":proposal["take_profit"]}
    out["compatibility"]={"maintain":"no_mutation_requested","repair_bracket":"manual_creation_verified_automatic_proposal_unverified",
        "update_bracket":"amendment_target_unverified","reduce":"reduce_only_exchange_test_pending","close":"reduce_only_exchange_test_pending"}[action]
    return out

def current_match(p,snapshot,now):
    if type(p.get("as_of")) is not int or not -1<=now-p["as_of"]<=180:return "proposal_expired"
    v=observe(snapshot,p["symbol"],now)
    if v["position_state"] not in ("long","short"):return "position_unavailable_or_flat"
    row=snapshot["positions"][0]
    if str(row.get("product_id"))!=str(p["product_id"]) or dec(v["size"])!=dec(p["before_size"]) or dec(v.get("entry_price"))!=dec(p["entry_price"]):return "position_changed"
    if v["bracket_state"]!=p["original_bracket_state"]:return "bracket_state_changed"
    if p["action"] in ("repair_bracket","update_bracket"):
        if snapshot.get("active_orders_complete") is not True or "active_orders" in (snapshot.get("errors") or {}):return "orders_unverified"
        if p["action"]=="repair_bracket" and snapshot.get("active_orders"):return "orders_changed"
        mark=dec(v.get("mark_price"));d=p["desired_triggers"];sl,tp=dec(d["stop_loss"]),dec(d["take_profit"])
        if mark is None or not (sl<mark<tp if p["before_size"]>0 else tp<mark<sl):return "trigger_geometry_changed"
    return "matching_observation_not_execution_authority"

def reconcile(p,snapshot,now,*,ack=None,order=None,fills=None,complete_fills=False):
    action=p["action"];v=observe(snapshot,p["symbol"],now)
    out={"version":VERSION,"action":action,"status":"unverified","execution_effect":"none","mode":"simulation_only"}
    if action=="maintain":
        out["status"]="no_mutation_requested";return out
    if v["position_state"] not in ("long","short","flat"):return out
    if v["position_state"]!="flat" and str(snapshot["positions"][0].get("product_id"))!=str(p["product_id"]):return out
    if action in ("repair_bracket","update_bracket"):
        out["acknowledgment"]=amendment_response(ack)
        if dec(v.get("size"))!=dec(p["before_size"]):out["status"]="position_changed";return out
        d=p["desired_triggers"]
        evidence=verify_fixture(snapshot,p["symbol"],now,p["before_size"],d["stop_loss"],d["take_profit"])
        out["status"]=evidence
        if evidence=="matching_triggers_observed" and out["acknowledgment"]!="acknowledged_unverified":out["status"]="matching_triggers_without_verified_ack"
        return out
    if not complete_fills or not isinstance(fills,list):out["status"]="fill_window_unverified";return out
    if not isinstance(order,dict) or dec(order.get("size"))!=dec(p["requested_reduction"]):
        out["status"]="requested_quantity_unverified";return out
    out["status"]=close_evidence(p["before_size"],v["size"],order,fills,p["product_id"])
    out["bracket_state"]=v["bracket_state"]
    out["target_size_observed"]=dec(v["size"])==dec(p["expected_size"])
    if out["status"] in ("full_close_observed","partial_close_observed"):
        if v["position_state"]=="flat" and v["bracket_state"]!="no_orders_observed":out["status"]="flat_residual_orders_unverified"
        elif v["position_state"]!="flat" and v["bracket_state"]!="matching_legs_observed":out["status"]="reduction_bracket_unverified"
    return out

def audit(rows,snapshot,now):
    out={"version":VERSION,"execution_effect":"none","status":"no_evaluated_proposal","latest":None}
    if not rows:return out
    import json
    try:
        row=rows[0];p=plan(json.loads(row["context"]),json.loads(row["result"])["proposal"])
        out.update(status="historical_plan_validated",latest={"id":row["id"],"action":p["action"],
          "before_size":p["before_size"],"expected_size":p["expected_size"],"compatibility":p["compatibility"],
          "current_observation":current_match(p,snapshot,now)})
    except (ValueError,TypeError,KeyError,ArithmeticError,AttributeError):
        out["status"]="historical_plan_unverified"
    return out
