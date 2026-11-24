"""M11 offline execution translation; no broker transport or live authority."""
from decimal import Decimal
from tradebot.ai_decision_v3 import validate
from tradebot.opportunity_journal_v3 import digest,ROUTE,known_route
from tradebot.position_observer_v3 import number

def translate(request,response,product,*,now):
    p=request["payload"]; s=p["symbol"]
    if s not in ROUTE or request.get("execution_authorized") is not False or digest(p)!=request["request_sha256"]:
        raise ValueError("invalid_preview_request")
    if not known_route(s,request["model_if_enabled"]) or not 0<=now-p["as_of"]<=150:
        raise ValueError("stale_or_wrong_route")
    if product.get("symbol")!=s or product.get("source")!="delta_demo_public_product" or not 0<=now-product["observed_at"]<=300:
        raise ValueError("wrong_or_stale_product")
    if type(product.get("product_id")) is not int or product["product_id"]<=0: raise ValueError("invalid_product")
    r=validate(response,request)
    base={"mode":"synthetic_execution_preview","symbol":s,"event_id":p["event_id"],
          "request_sha256":request["request_sha256"],"response_sha256":digest(r),
          "execution_authorized":False,"orders_submitted":0,"action":r["action"]}
    if r["action"]=="WAIT": return dict(base,entry=None,protection=None)
    plan=r["plan"]; tick=number(product["tick_size"],True)
    prices={k:number(plan[k],True) for k in ("entry_reference","stop_loss","take_profit")}
    if any(x%tick for x in prices.values()): raise ValueError("unaligned_price_no_rounding")
    # Existing authorized executor must enforce budget, leverage and actual fill protection.
    # No broker-callable client or submission function is exposed here.
    identity=digest([s,p["event_id"],"entry"])[:32]
    entry={"product_id":product["product_id"],"side":"buy" if r["action"]=="LONG" else "sell",
           "contracts":plan["contracts"],"kind":plan["entry_type"],"reference":str(prices["entry_reference"]),
           "preview_client_id":identity,"leverage":plan["leverage"],"margin_quote":plan["margin_quote"]}
    protection={"stop_loss":str(prices["stop_loss"]),"take_profit":str(prices["take_profit"]),
                "quantity_basis":"actual_filled_contracts","direction":r["action"]}
    return dict(base,entry=entry,protection=protection)

def observe_fixture(preview,receipt):
    """A synthetic receipt is never evidence of a live broker fill."""
    if preview.get("mode")!="synthetic_execution_preview" or preview.get("execution_authorized") is not False or preview.get("entry") is None:
        raise ValueError("entry_preview_required")
    entry=preview["entry"]
    unknown={"state":"unknown_requires_reconciliation","filled_contracts":None,"broker_verified":False}
    if not isinstance(receipt,dict): return unknown
    if receipt.get("source")!="synthetic_fixture" or receipt.get("client_order_id")!=entry["preview_client_id"] or receipt.get("symbol")!=preview["symbol"] or receipt.get("product_id")!=entry["product_id"] or receipt.get("side")!=entry["side"]:
        return unknown
    q=receipt.get("filled_contracts"); status=receipt.get("status")
    if type(q) is not int or not 0<=q<=entry["contracts"]: return unknown
    if status=="rejected" and q==0: state="fixture_rejected"
    elif status=="open" and q==0: state="fixture_pending"
    elif status=="open" and 0<q<entry["contracts"]: state="fixture_partial"
    elif status=="closed" and q==entry["contracts"]: state="fixture_filled"
    elif entry.get("kind")=="MARKET" and status in ("cancelled","expired") and q<entry["contracts"]: state="fixture_"+status
    else: return unknown
    return {"state":state,"filled_contracts":q,"broker_verified":False}
