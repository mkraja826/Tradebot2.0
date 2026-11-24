"""Public product specifications and isolated account evidence interface."""
from decimal import Decimal,InvalidOperation
from time import time
from tradebot.market_data_v3 import MARKETS,public_client
from tradebot.delta import DEMO_API

def decimal_text(value):
    try: d=Decimal(str(value))
    except (InvalidOperation,ValueError): raise ValueError("invalid_decimal") from None
    if not d.is_finite() or d<=0: raise ValueError("invalid_decimal")
    return str(d)

def product_spec(raw,symbol,observed_at):
    units={"BTCUSD":"BTC","XAUTUSD":"XAUT"}
    if symbol not in MARKETS or raw.get("symbol")!=symbol or raw.get("contract_type")!="perpetual_futures":
        raise ValueError("wrong_product")
    if raw.get("state")!="live" or raw.get("trading_status")!="operational":
        raise ValueError("product_not_operational")
    if type(raw.get("id")) is not int or raw["id"]<=0 or raw.get("contract_unit_currency")!=units[symbol]:
        raise ValueError("invalid_product_identity")
    if any(raw.get(k,{}).get("symbol")!="USD" for k in ("quoting_asset","settling_asset")):
        raise ValueError("unexpected_currency")
    return {"symbol":symbol,"product_id":raw["id"],"contract_type":"perpetual_futures",
            "contract_value":decimal_text(raw["contract_value"]),"contract_unit_currency":units[symbol],
            "tick_size":decimal_text(raw["tick_size"]),"quote_currency":"USD","settlement_currency":"USD",
            "initial_margin_raw":decimal_text(raw["initial_margin"]),"maintenance_margin_raw":decimal_text(raw["maintenance_margin"]),
            "max_leverage":None,"source":"delta_demo_public_product","observed_at":observed_at}

def collect_specs(client=None):
    c=public_client() if client is None else client
    if getattr(c,"base_url",None)!=DEMO_API or getattr(c,"allow_orders",None) is not False:
        raise ValueError("read_only_demo_required")
    out={}
    for s in MARKETS:
        try:
            p=c._request("GET","/v2/products/"+s)["result"]
            out[s]={"status":"ready","data":product_spec(p,s,int(time()))}
        except Exception as e: out[s]={"status":"unavailable","reason":type(e).__name__}
    return out

def account_unavailable(symbol):
    if symbol not in MARKETS: raise ValueError("unknown_symbol")
    return {"symbol":symbol,"subaccount":"BTC" if symbol=="BTCUSD" else "GOLD",
            "status":"unavailable","signed_account_verified":False,
            "reason":"fresh_signed_wallet_and_margin_evidence_not_connected"}
