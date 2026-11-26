"""LR-V4-B management adapter. Not wired into the running service.

Uses the existing demo management executor and its durable mutation journal.
Only a receipt-linked, terminal flat-to-open LR-V4-B entry is eligible.
"""
import hashlib
import json
import math
import sqlite3
import time
from decimal import ROUND_FLOOR, ROUND_CEILING
from .broker import DeltaDemo, DEMO_API
from .execution import product_for
from .lifecycle import pages, normalize_fill
from .performance import dec, stamp
from .lr_v4b import bracket, _candles, _ema
from .lr_v4b_attribution import Attribution, management_proposal
from .management_shadow import ManagementShadow, context_for, validate


def rounded(value,tick,rounding):
    value,tick=dec(value),dec(tick)
    if value is None or tick is None or value<=0 or tick<=0:
        raise ValueError("invalid tick or price")
    return (value/tick).to_integral_value(rounding=rounding)*tick


def terminal_entry(fills,pos,intent,receipt,cid):
    """Reconstruct a terminal entry, including multiple fills or cancelled remainder."""
    if len(fills)<2 or any(stamp(f) is None for f in fills):
        return None
    rows=sorted(fills,key=stamp)
    oid=str(receipt.get("id"))
    q=dec(pos.get("size"))
    avg=dec(pos.get("entry_price"))
    wanted=dec(intent.get("size"))
    ordered=dec(receipt.get("size"))
    remainder=dec(receipt.get("unfilled_size"))
    if (receipt.get("id") is None or receipt.get("client_order_id")!=cid
            or receipt.get("reduce_only") is not False or q is None or not q
            or avg is None or avg<=0 or wanted is None or wanted<=0
            or ordered!=wanted or remainder is None or not 0<=remainder<ordered
            or receipt.get("state") not in ("closed","cancelled","canceled")
            or (receipt.get("state")=="closed" and remainder!=0)):
        return None
    pid=str(pos.get("product_id"))
    side="buy" if q>0 else "sell"
    sign=1 if q>0 else -1
    if (receipt.get("side")!=side or intent.get("side")!=side
            or str(receipt.get("product_id"))!=pid or str(intent.get("product_id"))!=pid
            or ordered-remainder!=abs(q)
            or any(dec(intent.get(k)) is None or dec(intent.get(k))<=0
                   or dec(intent.get(k))!=dec(receipt.get("bracket_"+k+"_price"))
                   for k in ("stop_loss","take_profit"))):
        return None
    i=len(rows)
    while i and str(rows[i-1].get("order_id"))==oid:
        i-=1
    if i==0 or i==len(rows) or dec((rows[i-1].get("new_position") or {}).get("size"))!=0:
        return None
    if any(str(f.get("order_id"))==oid for f in rows[:i]):
        return None
    if len({stamp(f) for f in rows[i-1:]})!=len(rows[i-1:]):
        return None
    ids=[str(f.get("id")) for f in rows[i:]]
    if any(f.get("id") is None for f in rows[i:]) or len(set(ids))!=len(ids):
        return None
    qty=dec(0);value=dec(0)
    for f in rows[i:]:
        size,price=dec(f.get("size")),dec(f.get("price"))
        if (str(f.get("product_id"))!=pid or f.get("side")!=side
                or size is None or size<=0 or price is None or price<=0):
            return None
        qty+=size
        value+=size*price
        if dec((f.get("new_position") or {}).get("size"))!=sign*qty:
            return None
    if qty!=abs(q) or value!=qty*avg:
        return None
    return {"entry_price":str(avg),"size":str(q),
            "first_fill_time":math.ceil(stamp(rows[i]).timestamp()),
            "last_fill_time":math.ceil(stamp(rows[-1]).timestamp())}


class LRManager:
    def __init__(self,executor):
        if not isinstance(executor.broker,DeltaDemo) or DEMO_API!="https://cdn-ind.testnet.deltaex.org":
            raise ValueError("demo client required")
        self.executor=executor
        self.broker=executor.broker
        self.db=executor.db
        Attribution(self.db)
        ManagementShadow(self.db)

    def owner(self,snapshot,product):
        """Fresh fill and order reads; never infer strategy from price or side."""
        positions=snapshot.get("positions")
        if not isinstance(positions,list) or len(positions)!=1:
            return None
        pos=positions[0]
        if not pos.get("created_at") or str(pos.get("product_id"))!=str(product["id"]):
            return None
        raw,complete=pages(self.broker.fills_page,product["id"])
        if not complete:
            return None
        fills=[normalize_fill(f)[1] for f in raw]
        if len(fills)<2 or any(stamp(f) is None for f in fills):
            return None
        fills.sort(key=stamp)
        oid=str(fills[-1].get("order_id"))
        candidates=[]
        for cid,side,stop,intent,detail in self.db.execute("""SELECT l.client_id,l.side,l.structural_stop,o.intent,o.detail
                FROM lr_v4b_entries l JOIN orders o ON o.client_id=l.client_id
                WHERE o.symbol='BTCUSD' AND o.status='acknowledged'"""):
            try:
                if str(json.loads(detail).get("id"))!=oid:
                    continue
                receipt=self.broker.order(cid)
                line=terminal_entry(fills,pos,json.loads(intent),receipt,cid)
                if line is None or (dec(line["size"])>0)!=(side=="buy"):
                    continue
                b=bracket(side,line["entry_price"],stop)
                candidates.append({**b,"side":side,"client_id":cid,"entry_order":oid,
                                   "position_created_at":pos["created_at"],
                                   "fill_time":line["last_fill_time"],"timeout_start":line["first_fill_time"]})
            except (ValueError,TypeError,KeyError,ArithmeticError):
                continue
        return candidates[0] if len(candidates)==1 else None

    def run(self,report,candles,*,enabled=False,now=None):
        if not enabled:
            return {"status":"disabled","execution_effect":"none"}
        if report.get("symbol")!="BTCUSD":
            return {"status":"wrong_market","execution_effect":"none"}
        now=int(time.time()) if now is None else now
        product=product_for(self.broker,"BTCUSD")
        snap=self.executor.reader.observe("BTCUSD",product["id"])
        owner=self.owner(snap,product)
        if owner is None:
            return {"status":"ownership_unverified","attempted":False}
        ctx=context_for(report,snap,product,now)
        if ctx is None or ctx.get("execution_identity") is None:
            return {"status":"position_context_unverified","owned":True,"attempted":False}
        p=ctx["position"]
        d=1 if owner["side"]=="buy" else -1
        tick=product["tick_size"]
        if now-owner["timeout_start"]>=3600:
            proposal={"symbol":"BTCUSD","action":"close","reason":"LR-V4-B 60-minute timeout"}
        elif p["bracket_state"]!="matching_legs_observed":
            return {"status":"bracket_unverified","owned":True,"attempted":False}
        else:
            legs={leg["type"]:dec(leg["trigger"]) for leg in p["legs"]}
            sl,tp=legs["stop_loss_order"],legs["take_profit_order"]
            target=rounded(owner["target"],tick,ROUND_CEILING if d==1 else ROUND_FLOOR)
            if tp!=target:
                proposal={"symbol":"BTCUSD","action":"update_bracket","stop_loss":float(sl),
                          "take_profit":float(target),"reason":"LR-V4-B actual-fill 2R target"}
            else:
                rows=_candles(candles)
                r=management_proposal(owner,float(sl),rows,_ema(rows),fill_time=owner["fill_time"],now=now)
                if r["action"]=="close_at_timeout":
                    proposal={"symbol":"BTCUSD","action":"close","reason":"LR-V4-B 60-minute timeout"}
                else:
                    candidate=rounded(r["stop"],tick,ROUND_FLOOR if d==1 else ROUND_CEILING)
                    if d*(candidate-sl)<=0:
                        return {"status":"maintain","owned":True,"attempted":False}
                    proposal={"symbol":"BTCUSD","action":"update_bracket","stop_loss":float(candidate),
                              "take_profit":float(tp),"reason":"LR-V4-B EMA9 after 0.5R"}
        try:
            proposal=validate(proposal,ctx)
        except ValueError:
            return {"status":"proposal_incompatible_with_current_bracket","owned":True,"attempted":False}
        # Separate namespace from periodic AI management (positive 5-minute buckets).
        # Only one LR management mutation per second and position/desired action.
        ident=hashlib.sha256(json.dumps([owner["client_id"],owner["position_created_at"],
            now,proposal],sort_keys=True).encode()).hexdigest()
        try:
            with self.db:
                self.db.execute("INSERT INTO management_shadow VALUES (?,?,?,?,?,'proposed',?,?)",
                    (ident,"BTCUSD",-now-1,now,"lr-v4b-deterministic",json.dumps(ctx,allow_nan=False),
                     json.dumps({"proposal":proposal},allow_nan=False)))
        except sqlite3.IntegrityError:
            return {"status":"already_reserved","owned":True,"attempted":False}
        return {**self.executor.execute("BTCUSD",ident,enabled=True),"owned":True}
