"""Signed demo execution-account diagnostic; not an order permit."""
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from tradebot.delta import DEMO_API
from tradebot.fire_account_guard import _require_flat_demo_exposure
from tradebot.signed_account_context_v3 import LABELS,read_signed_context
from tradebot.owner_connectivity_bridge_v3 import AccountReader
from tradebot.research_collector_v3 import atomic_json

def project_leverage(setting,account):
    """Configured leverage and already-blocked order margin are observations, not quotes."""
    pid=account["product"]["product_id"]
    if str(setting.get("product_id"))!=str(pid):raise ValueError("wrong_product")
    def amount(v):
        if isinstance(v,bool):raise ValueError("invalid_amount")
        try:d=Decimal(str(v))
        except (InvalidOperation,ValueError):raise ValueError("invalid_amount") from None
        if not d.is_finite() or d<0:raise ValueError("invalid_amount")
        return d
    configured=amount(setting["leverage"])
    blocked=amount(setting["order_margin"])
    if configured<=0 or configured!=amount(account["configured_leverage"]):raise ValueError("leverage_mismatch")
    return dict(status="signed_setting_observed",configured_leverage=str(configured),
                within_existing_20x_ceiling=configured<=20,blocked_order_margin_zero=blocked==0,
                actual_order_margin_verified=False,account_maximum_leverage_verified=False,
                order_mutation_permission_verified=False,execution_authorized=False)

def inspect(symbol,child,parent,*,clock=lambda:datetime.now(timezone.utc)):
    if symbol not in LABELS:raise ValueError("wrong_symbol")
    out=dict(status="unavailable",identity_verified=False,flat_exposure_verified=False,
             execution_client_verified=False,execution_authorized=False,paid_dispatch_authorized=False)
    for c in (child,parent):
        if getattr(c,"base_url",None)!=DEMO_API or getattr(c,"allow_orders",None) is not False:
            return dict(out,stage="readonly_demo_required")
    try:
        reader=AccountReader(child,symbol)
        a=read_signed_context(symbol,reader,AccountReader(parent),clock=clock)
        if a["symbol"]!=symbol or a["subaccount"]!=LABELS[symbol] or a["signed_account_verified"] is not True or a["wallet_receipt_verified"] is not True:
            raise ValueError("identity_unverified")
        out.update(identity_verified=True,observed_at=a["observed_at"],status="signed_readonly_identity_verified")
    except Exception as exc:
        return dict(out,stage="signed_identity",reason=type(exc).__name__)
    try:
        # Diagnostic only; this internal exposure function is not a release gate.
        x=_require_flat_demo_exposure(child,selected_symbol=symbol,selected_product_id=a["product"]["product_id"])
        if (x["account_flat_verified"] is not True
            or type(x["open_positions"]) is not int or x["open_positions"]!=0
            or type(x["open_orders"]) is not int or x["open_orders"]!=0):
            raise ValueError("flatness_unverified")
        out.update(flat_exposure_verified=True,status="signed_readonly_exposure_verified")
    except Exception as exc:
        out.update(stage="account_wide_exposure",reason=type(exc).__name__)
    out["leverage_evidence"]={"status":"unavailable","execution_authorized":False}
    if out["flat_exposure_verified"]:
        try:
            pid=a["product"]["product_id"]
            setting=reader._request("GET",f"/v2/products/{pid}/orders/leverage",auth=True)["result"]
            out["leverage_evidence"]=project_leverage(setting,a)
        except Exception as exc:
            out["leverage_evidence"]["reason"]=type(exc).__name__
    out["remaining"]=["separate_execution_permission_verification","existing_release_gates","actual_order_margin_and_leverage","broker_execution_commissioning"]
    return out

def collect(root,children,parent,*,clock=lambda:datetime.now(timezone.utc)):
    out=dict(mode="execution_account_diagnostic_only",markets={},orders_submitted=0,paid_ai_requests=0,execution_authorized=False)
    for s in LABELS:out["markets"][s]=inspect(s,children.get(s),parent,clock=clock)
    out["checked_at"]=int(clock().timestamp())
    atomic_json(Path(root)/"m23-execution-account-v3.json",out)
    return out
