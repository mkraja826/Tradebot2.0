"""Local synthetic lifecycle evidence. No broker client or order submission."""
from pathlib import Path
from contextlib import closing
from decimal import Decimal,InvalidOperation
import json,sqlite3
from tradebot.opportunity_journal_v3 import canonical,digest
from tradebot.execution_preview_v3 import observe_fixture

def project(preview,receipt,protections):
    r=observe_fixture(preview,receipt)
    out={"mode":"synthetic_lifecycle_observation","entry_state":r["state"],
        "filled_contracts":r["filled_contracts"],"protection_state":"unknown",
        "broker_verified":False,"settlement_verified":False,"execution_authorized":False}
    q=r["filled_contracts"]
    if q is None: return out
    if q==0:
        out["protection_state"]="not_required" if protections==[] else "unexpected_protection"
        return out
    e=preview["entry"]; p=preview["protection"]; side="sell" if e["side"]=="buy" else "buy"
    expected={"stop_loss":Decimal(p["stop_loss"]),"take_profit":Decimal(p["take_profit"])}
    ids=set(); seen=set()
    try:
        if not isinstance(protections,list) or len(protections)!=2: raise ValueError()
        for x in protections:
            kind=x["kind"]; oid=x["order_id"]
            if (x["source"]!="synthetic_fixture" or x["symbol"]!=preview["symbol"] or
                x["product_id"]!=e["product_id"] or x["parent_client_id"]!=e["preview_client_id"] or
                x["side"]!=side or x["reduce_only"] is not True or x["state"]!="pending" or
                type(x["contracts"]) is not int or x["contracts"]!=q or
                not isinstance(oid,str) or not oid or oid in ids or kind in seen or Decimal(str(x["trigger"]))!=expected[kind]):
                raise ValueError()
            ids.add(oid);seen.add(kind)
        out["protection_state"]="fixture_bracket_matched"
    except (ValueError,TypeError,KeyError,InvalidOperation):
        out["protection_state"]="fixture_protection_unverified"
    return out

class LifecycleLedger:
    def __init__(self,path):
        self.path=Path(path)
        if self.path.is_symlink(): raise ValueError("untrusted_path")
        with closing(self.connect()) as db,db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS entries(event_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,preview_hash TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations(event_id TEXT NOT NULL,stamp INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(event_id,stamp),FOREIGN KEY(event_id) REFERENCES entries(event_id));
            """)
            for table in ("entries","observations"):
                for op in ("UPDATE","DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable evidence'); END")
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5);db.execute("PRAGMA foreign_keys=ON");return db
    def reserve(self,p):
        if p.get("mode")!="synthetic_execution_preview" or p.get("execution_authorized") is not False or p.get("orders_submitted")!=0: raise ValueError("simulation_only")
        if p["action"]=="WAIT": return "no_order"
        if p["action"] not in ("LONG","SHORT") or not p.get("entry") or not p.get("protection"): raise ValueError("invalid_preview")
        h=digest(p);eid=p["event_id"]
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT preview_hash FROM entries WHERE event_id=?",(eid,)).fetchone()
            if row:
                if row[0]!=h: raise ValueError("conflicting_preview")
                return "already_reserved"
            db.execute("INSERT INTO entries VALUES(?,?,?,?)",(eid,p["symbol"],h,canonical(p)))
        return "reserved"

    def observe(self,p,receipt,protections,*,stamp):
        if type(stamp) is not int or stamp<=0: raise ValueError("invalid_stamp")
        if p.get("mode")!="synthetic_execution_preview" or p.get("execution_authorized") is not False: raise ValueError("simulation_only")
        result=project(p,receipt,protections);eid=p["event_id"]
        item={"observation":result,"receipt":receipt,"protections":protections,"stamp":stamp}
        body=canonical(item)
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT preview_hash FROM entries WHERE event_id=?",(eid,)).fetchone()
            if not row or row[0]!=digest(p): raise ValueError("unreserved_preview")
            old=db.execute("SELECT stamp,payload FROM observations WHERE event_id=? ORDER BY stamp DESC LIMIT 1",(eid,)).fetchone()
            if old:
                if stamp<old[0]: raise ValueError("out_of_order")
                if stamp==old[0]:
                    if body!=old[1]: raise ValueError("conflicting_observation")
                    return "duplicate"
            # Unknown observations do not erase prior cumulative fill evidence.
            prior=db.execute("SELECT payload FROM observations WHERE event_id=? AND json_extract(payload,'$.observation.filled_contracts') IS NOT NULL ORDER BY stamp DESC LIMIT 1",(eid,)).fetchone()
            if prior and result["filled_contracts"] is not None:
                a=json.loads(prior[0])["observation"]; b=result
                if b["filled_contracts"]<a["filled_contracts"]: raise ValueError("decreasing_fill")
                if a["entry_state"] in ("fixture_filled","fixture_rejected","fixture_cancelled","fixture_expired") and (a["entry_state"],a["filled_contracts"])!=(b["entry_state"],b["filled_contracts"]):
                    raise ValueError("terminal_entry_conflict")
                if a["filled_contracts"]>0 and b["entry_state"]=="fixture_rejected": raise ValueError("rejected_after_fill")
            db.execute("INSERT INTO observations VALUES(?,?,?)",(eid,stamp,body))
        return result

def fixture_receipt(p,q,status):
    e=p["entry"]
    return {"source":"synthetic_fixture","symbol":p["symbol"],"product_id":e["product_id"],
        "side":e["side"],"client_order_id":e["preview_client_id"],"filled_contracts":q,"status":status}

def fixture_protections(p,q):
    e=p["entry"]
    return [{"source":"synthetic_fixture","symbol":p["symbol"],"product_id":e["product_id"],
        "parent_client_id":e["preview_client_id"],"side":"sell" if e["side"]=="buy" else "buy",
        "reduce_only":True,"state":"pending","contracts":q,"kind":k,
        "order_id":"fixture-"+k,"trigger":p["protection"][k]} for k in ("stop_loss","take_profit")]
