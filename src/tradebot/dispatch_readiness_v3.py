"""Read-only dispatch readiness preview. Never contacts the model provider."""
from pathlib import Path
from time import time
import json,sqlite3
from contextlib import closing
from tradebot.dashboard_context_v3 import read_accounts
from tradebot.product_context_v3 import collect_specs
from tradebot.model_wire_v3 import build_request,MODEL_IDS
from tradebot.research_collector_v3 import atomic_json

def assess(event,account,product,*,now):
    if event is None: return {"status":"no_opportunity","wire_prepared":False}
    s=event["symbol"]
    if not 0<=now-event["as_of"]<=150: return {"status":"expired","wire_prepared":False}
    if product.get("status")!="ready": return {"status":"product_unavailable","wire_prepared":False}
    try: wire=build_request(event,product["data"],now=now,account_context=account)
    except (ValueError,KeyError,TypeError): return {"status":"invalid_context","wire_prepared":False}
    reason="account_halted" if account.get("halted") is True else "signed_margin_context_incomplete"
    return {"status":reason,"wire_prepared":True,"event_id":event["event_id"],
            "request_sha256":wire["request"]["request_sha256"],"model_id":wire["body"]["model"],
            "execution_authorized":False,"paid_dispatch_authorized":False}

def native_equity_context(root,symbol,*,now):
    """Expose the existing native state to execution readiness diagnostics."""
    from tradebot.admin_v3 import status
    out=dict(status="unavailable",execution_authorized=False,policy_deployed=False)
    try:
        a=status(Path(root)/"v3-equity-state.sqlite",symbol)
        age=now-a["last_observed_us"]/1000000
        if age<0:raise ValueError("future_observation")
        periods=a["observed_periods"]
        return dict(out,status="stored_evidence" if age<=180 else "stale_evidence",
            observation_age_seconds=round(age,3),
            observed_raw_breaches=[k for k,v in periods.items() if v["observed_breach"] is True],
            unresolved_openings=[k for k in ("daily","weekly") if periods[k]["opening_verified"] is not True],
            historical_loss_reconciled=a["historical_loss_reconciled"],
            broker_finality_verified=a["broker_finality_verified"])
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):return out

def preview(root,*,account_reader=read_accounts,spec_reader=collect_specs,clock=time):
    root=Path(root); accounts=account_reader(); specs=spec_reader(); now=int(clock())
    result={"mode":"read_only_preview","checked_at":now,"markets":{},"paid_ai_requests":0,"orders_submitted":0}
    uri=(root/"opportunities-v3.sqlite").resolve().as_uri()+"?mode=ro"
    with closing(sqlite3.connect(uri,uri=True)) as db:
        for s in MODEL_IDS:
            row=db.execute("SELECT payload FROM events WHERE symbol=? ORDER BY as_of DESC,event_id DESC LIMIT 1",(s,)).fetchone()
            a=accounts[s]; p=specs[s]
            item=assess(json.loads(row[0]) if row else None,a,p,now=now)
            item["account_status"]=a["status"]; item["isolated_identity_verified"]=a.get("signed_account_verified",False)
            item["halted"]=a.get("halted"); item["product_status"]=p["status"]
            item["native_equity"]=native_equity_context(root,s,now=now)
            result["markets"][s]=item
    atomic_json(root/"dispatch-readiness-v3.json",result)
    return result
