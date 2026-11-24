"""Offline limit-entry lifecycle evidence. No transport or execution authority."""
import json,sqlite3
from pathlib import Path
from contextlib import closing
from tradebot.opportunity_journal_v3 import canonical,digest
from tradebot.synthetic_lifecycle_v3 import project

TERMINAL={"filled","cancelled","expired","rejected"}
def scope(p):
    e=p["entry"]
    if (p.get("mode")!="synthetic_execution_preview" or p.get("execution_authorized") is not False
        or p.get("orders_submitted")!=0 or e.get("kind")!="LIMIT"
        or p.get("symbol") not in ("BTCUSD","XAUTUSD") or p.get("action") not in ("LONG","SHORT")
        or type(e["contracts"]) is not int or e["contracts"]<1
        or e["side"]!=("buy" if p["action"]=="LONG" else "sell")):raise ValueError("limit_fixture_required")
    return e

def observation(p,r,brackets,*,stamp,expires):
    e=scope(p);n=e["contracts"]
    out=dict(state="unknown",filled=None,remaining=None,protection="unknown",
             expiry_elapsed=stamp>=expires,cancellation_confirmed=False,
             execution_authorized=False,broker_verified=False)
    if not isinstance(r,dict):return out
    if (r.get("source")!="synthetic_fixture" or r.get("symbol")!=p["symbol"]
        or r.get("product_id")!=e["product_id"] or r.get("side")!=e["side"]
        or r.get("client_order_id")!=e["preview_client_id"]):return out
    q=r.get("filled_contracts");state=r.get("status")
    if type(q) is not int or not 0<=q<=n:return out
    if not ((state=="open" and q<n) or (state=="filled" and q==n)
         or (state in ("cancelled","expired") and q<n)
         or (state=="rejected" and q==0)):return out
    # Reuse exact synthetic bracket ownership/quantity checks; cancellation
    # changes only the unfilled remainder, never the acquired exposure.
    b=project(p,dict(r,status="closed" if q==n else "open"),brackets)
    return dict(out,state=state,filled=q,remaining=n-q if state=="open" else 0,
                protection=b["protection_state"],cancellation_confirmed=state=="cancelled")

class LimitLedger:
    def __init__(self,path):
        self.path=Path(path)
        if self.path.is_symlink():raise ValueError("untrusted_path")
        with closing(self.connect()) as db,db:
            db.executescript("""CREATE TABLE IF NOT EXISTS entries(event TEXT PRIMARY KEY,hash TEXT NOT NULL,reserved INTEGER NOT NULL,expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS observations(event TEXT NOT NULL,stamp INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(event,stamp),FOREIGN KEY(event) REFERENCES entries(event));""")
            for table in ("entries","observations"):
                for op in ("UPDATE","DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{op} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable evidence'); END")
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5);db.execute("PRAGMA foreign_keys=ON");return db
    def reserve(self,p,*,now,expires):
        scope(p)
        if type(now) is not int or type(expires) is not int or not 0<now<expires:raise ValueError("invalid_expiry")
        key=p["event_id"];h=digest(p)
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT hash,reserved,expires FROM entries WHERE event=?",(key,)).fetchone()
            if row:
                if row[0]!=h or row[2]!=expires:raise ValueError("reservation_conflict")
                return "already_reserved"
            db.execute("INSERT INTO entries VALUES(?,?,?,?)",(key,h,now,expires))
        return "reserved"

    def observe(self,p,r,brackets,*,stamp):
        scope(p)
        if type(stamp) is not int:raise ValueError("invalid_stamp")
        key=p["event_id"]
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT hash,reserved,expires FROM entries WHERE event=?",(key,)).fetchone()
            if not row or row[0]!=digest(p) or stamp<row[1]:raise ValueError("invalid_reservation")
            a=observation(p,r,brackets,stamp=stamp,expires=row[2])
            body=canonical(dict(observation=a,receipt=r,brackets=brackets))
            latest=db.execute("SELECT stamp,payload FROM observations WHERE event=? ORDER BY stamp DESC LIMIT 1",(key,)).fetchone()
            if latest:
                if stamp<latest[0]:raise ValueError("out_of_order")
                if stamp==latest[0]:
                    if body!=latest[1]:raise ValueError("conflicting_observation")
                    return "duplicate"
            prior=db.execute("SELECT payload FROM observations WHERE event=? AND json_extract(payload,'$.observation.filled') IS NOT NULL ORDER BY stamp DESC LIMIT 1",(key,)).fetchone()
            if prior and a["filled"] is not None:
                old=json.loads(prior[0])["observation"]
                if a["filled"]<old["filled"]:raise ValueError("decreasing_fill")
                if old["state"] in TERMINAL and (a["state"],a["filled"])!=(old["state"],old["filled"]):raise ValueError("terminal_conflict")
            db.execute("INSERT INTO observations VALUES(?,?,?)",(key,stamp,body))
        return a

    def status(self,p,*,now):
        scope(p)
        if type(now) is not int:raise ValueError("invalid_stamp")
        with closing(self.connect()) as db:
            entry=db.execute("SELECT hash,reserved,expires FROM entries WHERE event=?",(p["event_id"],)).fetchone()
            if not entry or entry[0]!=digest(p) or now<entry[1]:raise ValueError("invalid_reservation")
            latest=db.execute("SELECT stamp,payload FROM observations WHERE event=? ORDER BY stamp DESC LIMIT 1",(p["event_id"],)).fetchone()
            known=db.execute("SELECT payload FROM observations WHERE event=? AND json_extract(payload,'$.observation.filled') IS NOT NULL ORDER BY stamp DESC LIMIT 1",(p["event_id"],)).fetchone()
        if latest and now<latest[0]:raise ValueError("future_observation")
        a=json.loads(latest[1])["observation"] if latest else {"state":"unknown","filled":None,"protection":"unknown"}
        k=json.loads(known[0])["observation"] if known else {}
        return dict(state=a["state"],last_known_filled=k.get("filled"),last_known_state=k.get("state"),
                    protection=a["protection"],expiry_elapsed=now>=entry[2],
                    cancellation_required=now>=entry[2] and a["state"]=="open",
                    reconciliation_required=a["state"]=="unknown",
                    execution_authorized=False,retry_authorized=False,broker_verified=False)
