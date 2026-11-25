"""Demo-only missing-bracket restoration with exact entry lineage and durable attempts."""
import json,sqlite3,time
from .broker import DEMO_API,DeltaDemo,error_detail
from .execution import product_for
from .lifecycle import pages,normalize_fill
from .performance import dec,stamp
from .bracket_contract import repair_status,fixture_payload,verify_fixture

VERSION="auto-bracket-repair-v1"

def entry_lineage(fills,position,receipts):
    """Require a single complete, flat-to-open fill as the latest exchange fill."""
    if not fills or not isinstance(position,dict):return None
    rows=[]
    for f in fills:
        t=stamp(f)
        if t is None:return None
        rows.append((t,f))
    rows.sort(key=lambda r:r[0])
    if len(rows)>1 and rows[-1][0]==rows[-2][0]:return None
    f=rows[-1][1];oid=f.get("order_id");q=dec(position.get("size"));price=dec(position.get("entry_price"))
    if q is None or q==0 or oid is None or f.get("id") is None or price is None:return None
    side="buy" if q>0 else "sell"
    if (str(f.get("product_id"))!=str(position.get("product_id")) or f.get("side")!=side
        or dec(f.get("size"))!=abs(q) or dec(f.get("price"))!=price
        or dec((f.get("new_position") or {}).get("size"))!=q):return None
    if len(rows)<2 or dec((rows[-2][1].get("new_position") or {}).get("size"))!=0:return None
    matches=[]
    for cid,intent,r in receipts:
        if str(r.get("id"))!=str(oid) or r.get("client_order_id")!=cid:continue
        if (str(r.get("product_id"))!=str(position.get("product_id")) or r.get("side")!=side
            or r.get("state")!="closed" or r.get("reduce_only") is not False
            or dec(r.get("size"))!=abs(q) or dec(r.get("unfilled_size"))!=0
            or dec(intent.get("size"))!=abs(q) or intent.get("side")!=side
            or str(intent.get("product_id"))!=str(position.get("product_id"))):continue
        sl,tp=dec(intent.get("stop_loss")),dec(intent.get("take_profit"))
        if sl is None or tp is None or sl<=0 or tp<=0:continue
        if sl!=dec(r.get("bracket_stop_loss_price")) or tp!=dec(r.get("bracket_take_profit_price")):continue
        matches.append({"entry_order":str(oid),"size":str(q),"entry_price":str(price),"stop":str(sl),"target":str(tp)})
    return matches[0] if len(matches)==1 else None

class BracketRepair:
    def __init__(self,broker,journal):
        if not isinstance(broker,DeltaDemo) or DEMO_API!="https://cdn-ind.testnet.deltaex.org":
            raise ValueError("Demo client required")
        self.broker=broker;self.db=journal.db
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS bracket_repairs (
                entry_order TEXT PRIMARY KEY, symbol TEXT NOT NULL, created INTEGER NOT NULL,
                status TEXT NOT NULL, detail TEXT NOT NULL)""")
    def observe(self,symbol,pid):
        rows=self.broker.margined_positions(pid)
        if not isinstance(rows,list):raise ValueError("position schema")
        positions=[]
        for row in rows:
            if not isinstance(row,dict):raise ValueError("position schema")
            if str(row.get("product_id"))!=str(pid):continue
            q=dec(row.get("size"))
            if q is None:raise ValueError("position size")
            if q:positions.append(row)
        orders,complete=pages(self.broker.active_orders_page,pid)
        return {"symbol":symbol,"observed":int(time.time()),"positions":positions,
                "active_orders":orders,"active_orders_complete":complete}
    def cycle(self,symbol,snapshot):
        # Snapshot is only a cheap candidate check; all mutation evidence is refreshed.
        status=repair_status(snapshot,symbol,int(time.time()))["status"]
        if status!="position_without_active_orders":
            return {"version":VERSION,"status":status,"attempted":False}
        try:return self._repair(symbol)
        except Exception as e:return {"version":VERSION,"status":"repair_check_error","attempted":False,**error_detail(e)}
    def _repair(self,symbol):
        def result(status,**kw):return {"version":VERSION,"status":status,"attempted":False,**kw}
        product=product_for(self.broker,symbol);pid=product["id"]
        first=self.observe(symbol,pid)
        if repair_status(first,symbol,int(time.time()))["status"]!="position_without_active_orders":return result("position_or_orders_changed")
        pos=first["positions"][0]
        raw,complete=pages(self.broker.fills_page,pid)
        if not complete:return result("fill_window_incomplete")
        fills=[normalize_fill(f)[1] for f in raw]
        receipts=[(cid,json.loads(i),json.loads(r)) for cid,i,r in self.db.execute(
            "SELECT client_id,intent,detail FROM orders WHERE symbol=? AND status='acknowledged'",(symbol,))]
        entry=entry_lineage(fills,pos,receipts)
        if entry is None:return result("entry_lineage_unverified")
        oid=entry["entry_order"];q=dec(entry["size"]);price=dec(entry["entry_price"])
        sl,tp=dec(entry["stop"]),dec(entry["target"])
        prior=self.db.execute("SELECT status FROM bracket_repairs WHERE entry_order=?",(oid,)).fetchone()
        if prior:return result("prior_attempt_no_retry",prior_status=prior[0])
        if not (sl<price<tp if q>0 else tp<price<sl):return result("fresh_ai_prices_required")
        # Re-read position and orders after fill lookup. Never overwrite any active order.
        second=self.observe(symbol,pid)
        if repair_status(second,symbol,int(time.time()))["status"]!="position_without_active_orders":return result("position_or_orders_changed")
        p=second["positions"][0]
        if dec(p.get("size"))!=q or dec(p.get("entry_price"))!=price or p.get("created_at")!=pos.get("created_at"):
            return result("position_or_orders_changed")
        ticker=self.broker.ticker(symbol);now=time.time_ns()//1000
        ts=ticker.get("timestamp")
        if ticker.get("symbol")!=symbol or ticker.get("product_id")!=pid or type(ts) is not int or not 0<=now-ts<=30_000_000:
            return result("ticker_unverified")
        try:payload=fixture_payload(pid,q,ticker.get("mark_price"),sl,tp,product.get("tick_size"))
        except ValueError:return result("fresh_ai_prices_required")
        detail={**entry,"mark":str(ticker["mark_price"]),"price_policy":"original_ai_prices_unchanged"}
        try:
            with self.db:self.db.execute("INSERT INTO bracket_repairs VALUES (?,?,?,?,?)",
                (oid,symbol,int(time.time()),"attempting",json.dumps(detail)))
        except sqlite3.IntegrityError:return result("prior_attempt_no_retry")
        try:
            ack=self.broker._request("POST","/v2/orders/bracket",payload=payload,auth=True)
            detail["response"]="acknowledged" if ack=={"success":True} else "unverified"
        except Exception as e:
            detail["response"]="unknown";detail["error"]=error_detail(e)
        status="unknown"
        try:
            after=self.observe(symbol,pid)
            status=verify_fixture(after,symbol,int(time.time()),q,sl,tp)
            if status=="matching_triggers_observed" and any(o.get("stop_trigger_method")!="mark_price" for o in after["active_orders"]):
                status="trigger_source_unverified"
        except Exception as e:detail["verification_error"]=error_detail(e)
        with self.db:self.db.execute("UPDATE bracket_repairs SET status=?,detail=? WHERE entry_order=?",(status,json.dumps(detail),oid))
        return {"version":VERSION,"status":status,"attempted":True}
