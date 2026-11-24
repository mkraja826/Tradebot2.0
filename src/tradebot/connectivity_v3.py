"""M11 connectivity diagnostics with injected authorized read-only clients.
No credential loading, completion transport or execution authority.
"""
from datetime import datetime,timezone
from tradebot.signed_account_context_v3 import read_signed_context
from tradebot.model_wire_v3 import check_catalogue,MODEL_IDS
from tradebot.dispatch_readiness_v3 import preview
from tradebot.research_collector_v3 import atomic_json
from pathlib import Path

def probe_clients(children,parent,provider,*,clock=lambda:datetime.now(timezone.utc)):
    result={"mode":"caller_supplied_client_diagnostic","markets":{},
            "paid_ai_requests":0,"orders_submitted":0,"execution_authorized":False}
    try: catalogue=check_catalogue(provider) if provider is not None else {}
    except Exception: catalogue={}
    for s,m in MODEL_IDS.items():
        item={"model_id":m,"catalogue_available":catalogue.get(s,{}).get("available"),
              "signed_wallet_verified":False,"configured_leverage_observed":False,
              "leverage_limit_verified":False,"status":"signed_context_unavailable"}
        try:
            a=read_signed_context(s,children.get(s),parent,clock=clock)
            item.update(signed_wallet_verified=a["wallet_receipt_verified"],
                configured_leverage_observed=a["configured_leverage"] is not None,
                leverage_limit_verified=a["leverage_limit"] is not None,
                status="signed_context_read_only")
        except Exception: pass
        result["markets"][s]=item
    return result

def refresh(root,**kwargs):
    root=Path(root)
    r=preview(root,**kwargs)
    result={"mode":"isolated_rebuild_connectivity","checked_at":r["checked_at"],
        "markets":{},"paid_ai_requests":0,"orders_submitted":0,
        "execution_authorized":False,"live_ai_verified":False}
    for s,a in r["markets"].items():
        result["markets"][s]={"model_id":MODEL_IDS[s],"product":a["product_status"],
            "dashboard_identity_verified":a["isolated_identity_verified"],
            "account_status":a["account_status"],"halted":a["halted"],
            "opportunity_status":a["status"],"wire_prepared":a["wire_prepared"],
            "signed_wallet_verified_in_rebuild":False,"provider_catalogue_verified_in_rebuild":False,
            "broker_execution_verified_in_rebuild":False,
            "remaining_prerequisites":["authorized_signed_client_integration","provider_authentication",
            "broker_order_interface_commissioning","existing_execution_protections"]}
    atomic_json(root/"connectivity-v3.json",result)
    return result
