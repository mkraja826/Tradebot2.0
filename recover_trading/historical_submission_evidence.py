"""Read-only evidence classification of ambiguous historical submissions."""
import json,sqlite3
from pathlib import Path
from contextlib import closing
from collections import Counter,defaultdict
VERSION="historical-submission-evidence-v1"

def classify(orders,snapshots,observed):
    evidence=defaultdict(list)
    for at,snapshot in snapshots:
        for ident,v in snapshot.get("order_lookup_diagnostics",{}).items():
            if isinstance(v,dict):evidence[ident].append((at,v))
    rows=[]
    for ident,status,intent,detail in orders:
        checks=sorted(evidence[ident],key=lambda x:x[0])
        missing={at for at,e in checks if e.get("http_status")==400 and e.get("exchange_code")=="order_not_found"}
        last=checks[-1] if checks else (None,{})
        receipt=observed.get(ident) or {}
        order=receipt.get("order") or {}
        matched=order.get("client_order_id")==ident and order.get("id") is not None and str(order.get("product_id"))==str(intent.get("product_id")) and order.get("side")==intent.get("side")
        original_http400=detail.get("category")=="http_error" and detail.get("http_status")==400
        if matched:classification="exchange_order_observed_review_required"
        elif last[0] in missing and original_http400:classification="original_http_400_and_lookup_not_found"
        elif last[0] in missing:classification="lookup_not_found_original_outcome_unverified"
        else:classification="insufficient_or_conflicting_lookup_evidence"
        rows.append({"client_id":ident,"journal_status":status,"classification":classification,
            "original_http_status":detail.get("http_status"),"original_exchange_code":detail.get("exchange_code"),
            "distinct_not_found_observation_times":len(missing),"last_lookup_epoch":last[0],
            "last_lookup_code":last[1].get("exchange_code"),"first_not_found_epoch":min(missing) if missing else None,
            "last_not_found_epoch":max(missing) if missing else None,"matched_observed_order":matched})
    return {"version":VERSION,"status":"observed","execution_effect":"none","counts":dict(Counter(r["classification"] for r in rows)),
        "unknown_count":len(rows),"rows":rows,"snapshot_window_count":len(snapshots),
        "limitations":["Original journal status preserved; missing order is not conclusive proof that an order never existed.",
        "Original HTTP 400 response is evidence of failure response, not exact rejection reason when code was unavailable.",
        "Recent archived lookup observations only; repeated timestamps are counted once. No historical order replay."]}

def report(root,symbol):
    try:
        with closing(sqlite3.connect((Path(root)/"orders.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            orders=[(i,s,json.loads(a),json.loads(d or "{}")) for i,s,a,d in db.execute("SELECT client_id,status,intent,detail FROM orders WHERE symbol=? AND status IN ('unknown','submitting')",(symbol,))]
            snapshots=[(at,json.loads(d)) for at,d in db.execute("SELECT observed,detail FROM lifecycle_snapshots WHERE symbol=? ORDER BY id DESC LIMIT 200",(symbol,))]
            observed={i:json.loads(d) for i,d in db.execute("SELECT client_id,detail FROM observed_orders WHERE symbol=?",(symbol,))}
        return classify(orders,snapshots,observed)
    except (sqlite3.Error,ValueError,KeyError,TypeError,AttributeError):return {"version":VERSION,"status":"unavailable","execution_effect":"none"}
