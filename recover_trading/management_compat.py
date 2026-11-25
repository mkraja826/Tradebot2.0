"""Offline compatibility evidence for position management. No order requests."""
import json,sqlite3
from pathlib import Path
from contextlib import closing
from collections import Counter
from .performance import dec,stamp
from .position_preview import observe

VERSION="management-compat-v1"

def amendment_response(envelope):
    # The documented bracket edit response is success-only. This is an
    # acknowledgment, not proof of changed triggers on an existing position.
    if not isinstance(envelope,dict):return "unverified"
    if envelope.get("success") is False:return "exchange_rejection"
    return "acknowledged_unverified" if envelope.get("success") is True else "unverified"

def close_evidence(before,after,order,fills,product_id):
    """Fixture-oriented verification, not a request builder or admission rule."""
    b,a=dec(before),dec(after)
    if b is None or not b or a is None or not isinstance(order,dict):
        return "unverified"
    oid=order.get("id");side="sell" if b>0 else "buy"
    if oid is None or str(order.get("product_id"))!=str(product_id) or order.get("side")!=side or order.get("reduce_only") is not True:
        return "identity_unverified"
    size,remaining=dec(order.get("size")),dec(order.get("unfilled_size"))
    if size is None or remaining is None or not 0<=remaining<=size<=abs(b):return "quantity_unverified"
    if order.get("state") not in ("closed","cancelled","canceled"):return "awaiting_terminal"
    if order.get("state")=="closed" and remaining!=0:return "quantity_unverified"
    matched=[]
    for f in fills:
        if str(f.get("order_id"))!=str(oid):continue
        q=dec(f.get("size"))
        if str(f.get("product_id"))!=str(product_id) or f.get("side")!=side or q is None or q<=0 or f.get("id") is None:
            return "fill_identity_unverified"
        matched.append((str(f["id"]),q))
    if len({i for i,q in matched})!=len(matched):return "fill_identity_unverified"
    total=sum(q for i,q in matched)
    if total!=size-remaining:return "fill_quantity_unverified"
    expected=b-total if b>0 else b+total
    if a!=expected:return "position_change_unverified"
    return "no_fill_observed" if total==0 else "full_close_observed" if a==0 else "partial_close_observed"

def historical_fills(fills):
    # Infer reductions only across adjacent, internally consistent observed
    # fills. No inference about reduce-only flags or causal management actions.
    counts=Counter();parsed=[]
    for f in fills:
        t=stamp(f)
        if t is None:counts["invalid_timestamp"]+=1
        else:parsed.append((t,f))
    parsed.sort(key=lambda x:x[0])
    previous=None;last_t=None
    for t,f in parsed:
        after=dec((f.get("new_position") or {}).get("size"));q=dec(f.get("size"));side=f.get("side")
        if after is None or q is None or q<=0 or side not in ("buy","sell"):
            counts["unverified"]+=1;previous=None;last_t=t;continue
        before=after-(q if side=="buy" else -q)
        if previous is None or previous!=before or last_t==t:
            counts["unanchored_or_discontinuous"]+=1
        elif before!=0 and after==0:counts["flat_after_reduction"]+=1
        elif before*after>0 and abs(after)<abs(before):counts["partial_reduction"]+=1
        elif before*after<0:counts["reversal"]+=1
        else:counts["other_consistent_fill"]+=1
        previous=after;last_t=t
    return dict(counts)

def audit(root,symbol,now):
    root=Path(root)
    out={"version":VERSION,"symbol":symbol,"execution_effect":"none","status":"unavailable",
         "amendment":"documented_target_identity_unverified",
         "reduce_only_close":"documented_not_tested_on_exchange",
         "response_contract":"success_only_ack_not_confirmation"}
    try:
        with closing(sqlite3.connect((root/"orders.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            row=db.execute("SELECT detail FROM lifecycle_snapshots WHERE symbol=? ORDER BY id DESC LIMIT 1",(symbol,)).fetchone()
            fills=[json.loads(x) for x, in db.execute("SELECT detail FROM observed_fills WHERE symbol=?",(symbol,))]
        view=observe(json.loads(row[0]) if row else None,symbol,now)
        out.update(status="observed",position_state=view["position_state"],bracket_state=view["bracket_state"],
            historical_fills=len(fills),fill_transitions=historical_fills(fills),
            limitations=["Historical reductions do not establish reduce-only order flags or bracket adjustment behavior.",
              "Documented bracket amendment requires an order ID; correct target for an already-filled entry is not established.",
              "No exchange mutation performed. No successful management API call has been demonstrated."])
    except (sqlite3.Error,ValueError,KeyError,TypeError,AttributeError,ArithmeticError):
        pass
    return out
