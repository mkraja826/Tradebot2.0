"""Read-only account commissioning evidence. Never loads or creates credentials."""
from pathlib import Path
from datetime import datetime,timezone
from tradebot.dashboard_context_v3 import read_accounts
from tradebot.signed_account_context_v3 import read_signed_context,LABELS
from tradebot.research_collector_v3 import atomic_json

def project(a,s):
    identity=a.get("signed_account_verified") is True and a.get("symbol")==s and a.get("subaccount")==LABELS[s]
    signed=identity and a.get("status")=="signed_read_only" and a.get("wallet_receipt_verified") is True
    return {"status":a.get("status","unavailable") if identity else "unavailable",
        "identity_verified":identity,"equity_observed":identity and a.get("net_equity_usd") is not None,
        "positions_observed":identity and isinstance(a.get("positions"),list),
        "open_order_count_observed":identity and type(a.get("open_order_count")) is int,
        "signed_wallet_receipt_verified":signed,
        "usd_wallet_available_balance_observed":signed and a.get("available_margin_usd") is not None,
        "configured_leverage_observed":signed and a.get("configured_leverage") is not None,
        "broker_margin_requirement_verified":False,"maximum_leverage_verified":False,
        "same_product_order_inventory_verified":signed and a.get("order_inventory_scope")=="account_wide_same_product",
        "halted":a.get("halted") if type(a.get("halted")) is bool else None,
        "execution_authorized":False,"paid_dispatch_authorized":False}

def tick(root,*,reader=read_accounts,children=None,parent=None,clock=lambda:datetime.now(timezone.utc)):
    try: dashboard=reader()
    except Exception: dashboard={}
    result={"mode":"signed_account_commissioning_read_only","markets":{},"execution_authorized":False,"orders_submitted":0,"paid_ai_requests":0}
    for s in LABELS:
        a=dashboard.get(s,{})
        item={"dashboard":project(a,s),"signed_client_status":"not_provisioned","signed":None}
        if children is not None and parent is not None and children.get(s) is not None:
            try:
                signed=read_signed_context(s,children[s],parent,clock=clock)
                item["signed"]=project(signed,s)
                item["signed_client_status"]="verified_read_only"
            except Exception as e: item["signed_client_status"]="unavailable:"+type(e).__name__
        item["commissioning_complete"]=False
        item["remaining"]=["broker_margin_requirement","maximum_leverage","authenticated_provider","separate_execution_commissioning"]
        if item["signed_client_status"]!="verified_read_only": item["remaining"].insert(0,"owner_provisioned_read_only_signed_clients")
        result["markets"][s]=item
    result["checked_at"]=int(clock().timestamp())
    atomic_json(Path(root)/"m15-account-connectivity-v3.json",result)
    return result
