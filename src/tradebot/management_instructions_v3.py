"""M8 management instruction contract; offline previews only."""
from tradebot.position_observer_v3 import number
from tradebot.opportunity_journal_v3 import digest,ROUTE

ACTIONS=("HOLD","MOVE_STOP","BREAKEVEN_STOP","MOVE_TARGET","PARTIAL_EXIT","CLOSE")
VERSION="management-v3.1"

def prepare(observation,spec,*,now):
    s=observation.get("symbol")
    if s not in ROUTE or observation.get("source")!="existing_signed_dashboard":
        raise ValueError("unknown_observation_source")
    if observation.get("status")!="open_protection_reported" or len(observation.get("positions",[]))!=1:
        raise ValueError("single_protected_position_required_for_preview")
    if not 0<=now-observation["observed_us"]/1e6<=60: raise ValueError("stale_observation")
    if spec.get("symbol")!=s or spec.get("source")!="delta_demo_public_product" or not 0<=now-spec["observed_at"]<=300:
        raise ValueError("wrong_or_stale_product")
    p=observation["positions"][0]
    for k in ("quantity","entry","mark","stop_loss","take_profit"): number(p[k],True)
    if p["side"] not in ("LONG","SHORT"): raise ValueError("invalid_side")
    payload={"version":VERSION,"symbol":s,"observation":observation,"product":spec}
    return {"context_id":digest(payload),"payload":payload,"model_if_enabled":ROUTE[s],
            "allowed_actions":ACTIONS,"mode":"offline_management_preview","execution_authorized":False}

def validate(request,response):
    if request.get("mode")!="offline_management_preview" or request.get("execution_authorized") is not False:
        raise ValueError("preview_only")
    p=request["payload"]
    if digest(p)!=request["context_id"]: raise ValueError("context_tampered")
    if not isinstance(response,dict) or set(response)!={"context_id","symbol","action","value","rationale"}:
        raise ValueError("invalid_instruction_fields")
    if response["context_id"]!=request["context_id"] or response["symbol"]!=p["symbol"]:
        raise ValueError("instruction_identity_mismatch")
    action=response["action"]; v=response["value"]
    if action not in ACTIONS or not isinstance(response["rationale"],str) or not response["rationale"].strip():
        raise ValueError("invalid_instruction")
    pos=p["observation"]["positions"][0]; side=pos["side"]
    qty,entry,mark,old_sl=(number(pos[k],True) for k in ("quantity","entry","mark","stop_loss"))
    if action in ("HOLD","CLOSE"):
        if v is not None: raise ValueError("unexpected_value")
    elif action=="PARTIAL_EXIT":
        if type(v) is not int or not 0<v<qty: raise ValueError("invalid_partial_quantity")
    else:
        level=number(v,True); tick=number(p["product"]["tick_size"],True)
        if level%tick: raise ValueError("unaligned_price")
        if action in ("MOVE_STOP","BREAKEVEN_STOP"):
            if not (old_sl<=level<mark if side=="LONG" else mark<level<=old_sl):
                raise ValueError("stop_not_tightened_or_wrong_side")
            if action=="BREAKEVEN_STOP" and level!=entry: raise ValueError("not_entry_price")
        elif not (level>mark if side=="LONG" else level<mark): raise ValueError("target_wrong_side")
    return {"instruction_id":digest(response),"response":response,"context":request,
            "mode":"offline_management_preview","execution_authorized":False,
            "orders_submitted":0,"scanner_control":False}
