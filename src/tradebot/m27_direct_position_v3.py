"""Dashboard-independent signed inventory observations; alert-only."""
from datetime import datetime
from tradebot.signed_account_context_v3 import LABELS

def project(s,a,*,now):
    out=dict(symbol=s,status="unknown",source="direct_signed_readonly",
             position_count=None,open_order_count=None,observed_at=None,
             execution_authorized=False,settlement_verified=False,
             protection_ownership_verified=False)
    try:
        if s not in LABELS or a["symbol"]!=s or a["subaccount"]!=LABELS[s] or a["status"]!="signed_read_only" or a["signed_account_verified"] is not True or a["wallet_receipt_verified"] is not True or a["execution_authorized"] is not False:
            return out
        t=datetime.fromisoformat(a["observed_at"])
        if t.tzinfo is None or not 0<=now-t.timestamp()<=60:return dict(out,reason="stale_observation")
        p=a["positions"];n=a["open_order_count"]
        if not isinstance(p,list) or len(p)>=10 or type(n) is not int or not 0<=n<=200 or a["order_inventory_scope"]!="account_wide_same_product":return out
        if any(x["symbol"]!=s for x in p):return out
        if not p:state="flat_reported" if n==0 else "flat_orders_present"
        else:state="open_bracket_reported" if len(p)==1 and n==2 and all(x.get("protection",{}).get("status")=="signed_pending_bracket" for x in p) else "open_protection_unverified"
        return dict(out,status=state,position_count=len(p),open_order_count=n,observed_at=t.isoformat())
    except (KeyError,ValueError,TypeError,AttributeError):return out
