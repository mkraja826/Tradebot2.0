"""LR-V4-B management adapter. Not wired into the running service.

Uses the existing demo management executor and its durable mutation journal.
Only a receipt-linked, single-fill flat-to-open LR-V4-B position is eligible.
"""
import hashlib
import json
import math
import sqlite3
import time
from decimal import ROUND_FLOOR, ROUND_CEILING
from .broker import DeltaDemo, DEMO_API
from .bracket_repair import entry_lineage
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
                line=entry_lineage(fills,pos,[(cid,json.loads(intent),receipt)])
                if line is None or (dec(line["size"])>0)!=(side=="buy"):
                    continue
                b=bracket(side,line["entry_price"],stop)
                candidates.append({**b,"side":side,"client_id":cid,"entry_order":oid,
                                   "position_created_at":pos["created_at"],
                                   "fill_time":math.ceil(stamp(fills[-1]).timestamp())})
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
        if now-owner["fill_time"]>=3600:
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
