"""Read-only demo contract risk metadata. No execution or margin authorization."""
from decimal import Decimal
from time import time
from pathlib import Path
from tradebot.market_data_v3 import public_client,MARKETS
from tradebot.delta import DEMO_API
from tradebot.product_context_v3 import product_spec
from tradebot.research_collector_v3 import atomic_json
from tradebot.owner_connectivity_bridge_v3 import read_report

def project(raw,s,now):
    spec=product_spec(raw,s,now)
    if raw.get("notional_type")!="vanilla":raise ValueError("unsupported_notional")
    out={}
    for k in ("initial_margin","maintenance_margin","initial_margin_scaling_factor","maintenance_margin_scaling_factor","max_leverage_notional","position_notional_limit","default_leverage","maker_commission_rate","taker_commission_rate"):
        v=Decimal(str(raw[k]))
        if not v.is_finite() or v<0:raise ValueError("invalid_reference")
        out[k]=str(v)
    if not 0<Decimal(out["maintenance_margin"])<=Decimal(out["initial_margin"])<=100:raise ValueError("invalid_margin")
    if min(Decimal(out[k]) for k in ("max_leverage_notional","position_notional_limit","default_leverage"))<=0:raise ValueError("invalid_limit")
    n=raw["position_size_limit"]
    if type(n) is not int or n<=0:raise ValueError("invalid_position_limit")
    return {"status":"public_reference_available","spec":spec,"risk_fields":out,"position_size_limit_raw":n,
            "actual_order_margin_verified":False,"account_max_leverage_verified":False,"execution_authorized":False}

def tick(root,*,client=None,clock=time):
    c=public_client() if client is None else client
    if getattr(c,"base_url",None)!=DEMO_API or getattr(c,"allow_orders",None) is not False:raise ValueError("read_only_demo_required")
    r={"mode":"demo_broker_reference_only","markets":{},"execution_authorized":False,"orders_submitted":0,"paid_ai_requests":0}
    for s in MARKETS:
        try:r["markets"][s]=project(c._request("GET","/v2/products/"+s)["result"],s,int(clock()))
        except Exception as exc:r["markets"][s]={"status":"reference_unavailable","reason":type(exc).__name__}
    r["checked_at"]=int(clock())
    r["account_monitor"]=read_report(root,now=r["checked_at"])
    atomic_json(Path(root)/"m20-broker-reference-v3.json",r)
    return r
