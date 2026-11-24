"""Independent M8 observation engine; no model calls, broker writes or approvals."""
from decimal import Decimal,InvalidOperation
from datetime import datetime,timezone
from tradebot.account_context_v3 import LABELS

def number(value,positive=False):
    try: x=Decimal(str(value))
    except (InvalidOperation,ValueError): raise ValueError("invalid_number") from None
    if not x.is_finite() or (positive and x<=0): raise ValueError("invalid_number")
    return x

def view(symbol,account,*,now):
    base={"symbol":symbol,"status":"unknown","reason":"account_evidence_unavailable"}
    try:
        if account.get("symbol")!=symbol or account.get("subaccount")!=LABELS[symbol] or account.get("signed_account_verified") is not True: return base
        at=datetime.fromisoformat(account["broker_checked_at"])
        if at.tzinfo is None or not 0<=now-at.timestamp()<=60: return dict(base,reason="stale_account_evidence")
        positions=account["positions"]; orders=account["open_order_count"]
        if not isinstance(positions,list) or len(positions)>=10 or type(orders) is not int or orders<0: return dict(base,reason="inventory_unverified")
        result=[]
        for p in positions:
            if p["symbol"]!=symbol: raise ValueError("wrong_symbol")
            qty=number(p["size"]); side="LONG" if qty>0 else "SHORT"
            if not qty or p["side"]!=side: raise ValueError("invalid_side")
            entry=number(p["entry"],True); pr=p.get("protection") or {}
            protected=False; sl=tp=None
            if pr.get("status")=="signed_pending_bracket" and pr.get("source")=="signed_pending_broker_orders":
                try:
                    a,b=number(pr["stop_loss"],True),number(pr["take_profit"],True)
                    protected=(a<entry<b if side=="LONG" else b<entry<a)
                    if protected: sl,tp=str(a),str(b)
                except (ValueError,KeyError): pass
            optional={}
            for k in ("mark","liquidation","unrealized_pnl"):
                try: optional[k]=str(number(p.get(k),k!="unrealized_pnl"))
                except ValueError: optional[k]=None
            result.append({"side":side,"quantity":str(abs(qty)),"entry":str(entry),
                           "protection":"broker_reported_bracket" if protected else "unverified",
                           "stop_loss":sl,"take_profit":tp,**optional})
        status="flat_observed" if not result and orders==0 else "flat_orders_present" if not result else "open_protection_reported" if all(p["protection"]=="broker_reported_bracket" for p in result) and orders>=2*len(result) else "open_protection_unverified"
        return {"symbol":symbol,"status":status,"observed_at":at.isoformat(),"observed_us":int(at.timestamp()*1000000),
                "positions":result,"open_order_count":orders,"source":"existing_signed_dashboard",
                "halted":account.get("halted"),"settlement_verified":False}
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        return dict(base,reason="invalid_account_evidence")

def structural(v):
    return {"status":v["status"],"open_order_count":v["open_order_count"],
            "positions":sorted([{k:p[k] for k in ("side","quantity","entry","protection","stop_loss","take_profit")} for p in v["positions"]],key=lambda p:tuple(str(p[k]) for k in sorted(p)))}
