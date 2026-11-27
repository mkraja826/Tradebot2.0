"""Gold V2 durable episode reconciliation. Research/preview only; no broker writes."""
import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from .position_preview import observe
from .management_executor import identity

VERSION="gold-v2-lifecycle.1"
SYMBOL="XAUTUSD"

def d(x):
    if isinstance(x,bool):raise ValueError("invalid_number")
    n=Decimal(str(x))
    if not n.is_finite():raise ValueError("invalid_number")
    return n

def timestamp(x):
    if not isinstance(x,str):raise ValueError("timestamp_required")
    t=datetime.fromisoformat(x.replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("timezone_required")
    return t.timestamp()

def encode(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)

def client_id(boundary):
    if type(boundary) is not int or boundary<=0 or boundary%300:raise ValueError("invalid_boundary")
    return sha256(("recover:"+sha256(f"gold-v2:{boundary}".encode()).hexdigest()).encode()).hexdigest()[:32]

def reconcile(seed,receipt,fills,reductions,snapshot,*,now,complete):
    """Replay a complete post-anchor fill slice from trusted exchange reads.

    seed must be reserved against a verified flat account before submission.
    reductions are terminal receipts for independently authorized reduce-only
    orders (including protective exits); no arbitrary same-side fills accepted.
    The caller must establish the completeness and account identity of reads.
    """
    def out(status,**kw):return {"version":VERSION,"symbol":SYMBOL,"status":status,"execution_effect":"none",**kw}
    if seed.get("symbol")!=SYMBOL or snapshot.get("symbol")!=SYMBOL:
        raise ValueError("wrong_symbol")
    if complete is not True:return out("fill_window_incomplete")
    try:
        cid=client_id(seed["signal_boundary"])
        pid=seed["product_id"];side=seed["side"];sign=1 if side=="buy" else -1
        if (type(pid) is not int or pid<=0 or side not in ("buy","sell")
            or seed["client_id"]!=cid or seed.get("flat_verified") is not True
            or not seed["signal_boundary"]<=seed["flat_observed_at"]<=now):
            return out("invalid_seed")
        anchor=seed["flat_observed_at"]
        expected=d(seed["size"])
        if expected<=0 or expected!=int(expected):return out("invalid_seed")
        if (receipt.get("client_order_id")!=cid or str(receipt.get("product_id"))!=str(pid)
            or receipt.get("side")!=side or receipt.get("reduce_only") is not False
            or receipt.get("id") is None or d(receipt["size"])!=expected):
            return out("entry_receipt_unverified")
        if receipt.get("state") not in ("closed","cancelled","canceled"):return out("entry_pending")
        remaining=d(receipt["unfilled_size"])
        if not 0<=remaining<=expected or (receipt["state"]=="closed" and remaining!=0):
            return out("entry_receipt_unverified")
        entry_qty=expected-remaining
        oid=str(receipt["id"]);allowed={};totals={}
        for r in reductions:
            rid=str(r["id"])
            if (rid==oid or rid in allowed or r.get("id") is None or str(r.get("product_id"))!=str(pid)
                or r.get("side")==side or r.get("side") not in ("buy","sell")
                or r.get("reduce_only") is not True or r.get("state") not in ("closed","cancelled","canceled")):
                return out("reduction_receipt_unverified")
            q,left=d(r["size"]),d(r["unfilled_size"])
            if not 0<=left<=q or (r["state"]=="closed" and left!=0):return out("reduction_receipt_unverified")
            allowed[rid]=q-left;totals[rid]=Decimal(0)
        rows=[];seen=set()
        for f in fills:
            t=timestamp(f["created_at"])
            if t<anchor:continue
            if t==anchor or t>now:return out("fill_time_unverified")
            if str(f.get("product_id"))!=str(pid):return out("wrong_fill_product")
            fid=str(f["id"])
            if f.get("id") is None or fid in seen:return out("duplicate_fill")
            seen.add(fid);rows.append((t,f))
        rows.sort(key=lambda x:x[0])
        if any(a[0]==b[0] for a,b in zip(rows,rows[1:])):return out("ambiguous_fill_order")
        quantity=Decimal(0);filled=Decimal(0);weighted=Decimal(0);last_entry=None;reduced=False
        for t,f in rows:
            q=d(f["size"]);p=d(f["price"]);rid=str(f["order_id"])
            if q<=0 or q!=int(q) or p<=0:return out("invalid_fill")
            if rid==oid and not reduced and f["side"]==side:
                quantity+=sign*q;filled+=q;weighted+=q*p;last_entry=t
            elif rid in allowed and f["side"]!=side and f["side"] in ("buy","sell"):
                if filled!=entry_qty or q>abs(quantity):return out("invalid_reduction")
                quantity-=sign*q;totals[rid]+=q;reduced=True
            else:return out("unattributed_fill")
            if d(f["new_position"]["size"])!=quantity:return out("fill_chain_mismatch")
        if filled!=entry_qty or totals!=allowed:return out("fill_quantity_unverified")
        v=observe(snapshot,SYMBOL,now)
        if v["position_state"] not in ("flat","long","short") or d(v["size"])!=quantity:
            return out("position_mismatch")
        if quantity==0:
            if v["bracket_state"]!="no_orders_observed":return out("residual_orders_unverified")
            return out("closed" if filled else "terminal_no_fill",size=0,fill_ids=sorted(seen))
        avg=d(receipt["average_fill_price"])
        if avg<=0 or weighted/filled!=avg or d(v["entry_price"])!=avg:
            return out("entry_price_unverified")
        if v["bracket_state"]!="matching_legs_observed" or len(snapshot["active_orders"])!=2:
            return out("bracket_coverage_unverified")
        if any(o.get("stop_trigger_method")!="mark_price" for o in snapshot["active_orders"]):
            return out("bracket_trigger_unverified")
        pos=snapshot["positions"][0];ident=identity(snapshot)
        if ident is None or str(pos.get("product_id"))!=str(pid):return out("position_identity_unverified")
        if timestamp(pos["created_at"])<anchor or timestamp(pos["created_at"])>last_entry:
            return out("position_lineage_unverified")
        initial_sl=d(seed["stop_loss"]);initial_tp=d(seed["take_profit"])
        if min(initial_sl,initial_tp)<=0 or d(receipt["bracket_stop_loss_price"])!=initial_sl or d(receipt["bracket_take_profit_price"])!=initial_tp:
            return out("initial_bracket_unverified")
        legs={l["type"]:d(l["trigger"]) for l in v["legs"]}
        if sign*(legs["stop_loss_order"]-initial_sl)<0:return out("stop_loosened")
        return out("owned_open",size=int(quantity),initial_filled_size=int(filled),
                   entry_price=str(avg),initial_stop=str(initial_sl),initial_target=str(initial_tp),
                   client_id=cid,identity=ident,view=v,reduced=reduced,
                   first_full_bar_close=(int(last_entry)//300+2)*300,fill_ids=sorted(seen))
    except (KeyError,TypeError,ValueError,ArithmeticError,AttributeError):
        return out("invalid_evidence")

class EpisodeJournal:
    """Local append-only evidence journal; never submits exchange requests."""
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=10)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS gold_v2_episodes(
          client_id TEXT PRIMARY KEY,seed TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS gold_v2_episode_observations(
          client_id TEXT NOT NULL, observed_at INTEGER NOT NULL, evidence TEXT NOT NULL,
          result TEXT NOT NULL, PRIMARY KEY(client_id,observed_at));
        """)
    def close(self):self.db.close()
    def reserve(self,seed):
        cid=client_id(seed["signal_boundary"])
        if seed.get("symbol")!=SYMBOL or seed.get("client_id")!=cid or seed.get("flat_verified") is not True:
            raise ValueError("invalid_seed")
        raw=encode(seed)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old=self.db.execute("SELECT seed FROM gold_v2_episodes WHERE client_id=?",(cid,)).fetchone()
            if old:
                if old[0]!=raw:raise ValueError("seed_conflict")
                return cid
            self.db.execute("INSERT INTO gold_v2_episodes VALUES (?,?)",(cid,raw))
        return cid
    def record(self,cid,receipt,fills,reductions,snapshot,*,now,complete):
        if type(now) is not int:raise ValueError("invalid_now")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row=self.db.execute("SELECT seed FROM gold_v2_episodes WHERE client_id=?",(cid,)).fetchone()
            if not row:raise ValueError("unknown_episode")
            evidence=encode({"receipt":receipt,"fills":fills,"reductions":reductions,"snapshot":snapshot,"complete":complete})
            old=self.db.execute("SELECT observed_at,evidence,result FROM gold_v2_episode_observations WHERE client_id=? ORDER BY observed_at DESC LIMIT 1",(cid,)).fetchone()
            if old and now<=old[0]:
                if now==old[0] and evidence==old[1]:return json.loads(old[2])
                raise ValueError("nonmonotonic_or_conflicting_observation")
            if old and json.loads(old[2])["status"] in ("closed","terminal_no_fill"):
                raise ValueError("terminal_episode")
            result=reconcile(json.loads(row[0]),receipt,fills,reductions,snapshot,now=now,complete=complete)
            self.db.execute("INSERT INTO gold_v2_episode_observations VALUES (?,?,?,?)",(cid,now,evidence,encode(result)))
        return result
