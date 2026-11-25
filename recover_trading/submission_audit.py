"""Read-only audit of submission context and documented exchange error categories."""
import hashlib,json,sqlite3
from collections import Counter,defaultdict
from contextlib import closing
from pathlib import Path
from .performance import dec

VERSION="submission-audit-v1"
def position_state(account,product):
    positions=account.get("positions")
    if not isinstance(positions,list) or not positions:return "unavailable"
    vals=[]
    for p in positions:
        if not isinstance(p,dict) or ("product_id" in p and str(p["product_id"])!=str(product.get("id"))):return "unavailable"
        # account_context obtains positions using the verified product-scoped GET;
        # Delta may omit product_id in its response.
        n=dec(p.get("size"))
        if n is None:return "unavailable"
        vals.append(n)
    if not any(vals):return "flat"
    if all(v<=0 for v in vals):return "short"
    if all(v>=0 for v in vals):return "long"
    return "mixed"

def audit(orders,contexts):
    counts=Counter();group=defaultdict(Counter);codes=Counter();rows=[]
    for client,status,intent,detail in orders:
        a=contexts.get(client,{}).get("demo_account",{})
        p=a.get("product",{})
        if p.get("id") is None or p.get("id")!=intent.get("product_id"):a={};p={}
        position=position_state(a,p)
        tick=dec(p.get("tick_size"))
        sl,tp=(dec(intent.get(k)) for k in ("stop_loss","take_profit"))
        aligned=(sl%tick==0 and tp%tick==0) if tick is not None and tick>0 and sl is not None and tp is not None else None
        code=detail.get("exchange_code")
        if code:codes[code]+=1
        counts[status]+=1;group[status][position]+=1
        rows.append({"status":status,"position_at_decision":position,"side":intent.get("side"),
            "tick_alignment":aligned,"http_status":detail.get("http_status"),"exchange_code":code})
    return {"version":VERSION,"status":"observed","submission_counts":dict(counts),
            "by_decision_position":{k:dict(v) for k,v in group.items()},"exchange_codes":dict(codes),
            "misaligned_brackets":sum(x["tick_alignment"] is False for x in rows),
            "unknown_tick_alignment":sum(x["tick_alignment"] is None for x in rows),
            "recent":rows[-100:],"execution_effect":"none",
            "limitations":["Position evidence is from decision time, not submission time; missing row product IDs inherit the archived product-scoped request identity.",
              "Association with existing positions is not proof of original failure cause.",
              "Unknown orders remain unknown; no retry, cancellation, or bracket change."]}

def read_audit(root,symbol):
    root=Path(root)
    try:
        with closing(sqlite3.connect((root/"decisions.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            contexts={hashlib.sha256(("recover:"+i).encode()).hexdigest()[:32]:json.loads(c) for i,c in db.execute("SELECT id,context FROM decisions WHERE symbol=?",(symbol,))}
        with closing(sqlite3.connect((root/"orders.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            orders=[(i,s,json.loads(a),json.loads(d or "{}")) for i,s,a,d in db.execute("SELECT client_id,status,intent,detail FROM orders WHERE symbol=? ORDER BY rowid",(symbol,))]
        return audit(orders,contexts)
    except (sqlite3.Error,ValueError,KeyError,TypeError,AttributeError,ArithmeticError):
        return {"version":VERSION,"status":"unavailable","execution_effect":"none"}
