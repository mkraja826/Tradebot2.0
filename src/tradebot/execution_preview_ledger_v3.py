"""Durable simulated reservation; never retries uncertain execution."""
import sqlite3
from contextlib import closing
from tradebot.opportunity_journal_v3 import canonical,digest
from tradebot.execution_preview_v3 import observe_fixture

class PreviewLedger:
    def __init__(self,path):
        self.path=path
        with closing(self.connect()) as db,db:
            db.execute("""CREATE TABLE IF NOT EXISTS reservations(
                event_id TEXT PRIMARY KEY,preview_hash TEXT NOT NULL,payload TEXT NOT NULL,
                state TEXT NOT NULL,updated INTEGER NOT NULL,receipt TEXT)""")
    def connect(self): return sqlite3.connect(self.path,timeout=10)
    def reserve(self,p,*,now):
        if p.get("mode")!="synthetic_execution_preview" or p.get("execution_authorized") is not False:
            raise ValueError("simulation_only")
        if p["action"]=="WAIT": return "no_order"
        if not p.get("entry"): raise ValueError("missing_entry")
        key=p["event_id"]; h=digest(p)
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT preview_hash,state FROM reservations WHERE event_id=?",(key,)).fetchone()
            if old:
                if old[0]!=h: raise ValueError("conflicting_preview")
                return "already_reserved"
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,NULL)",(key,h,canonical(p),"reserved",now))
        return "reserved"
    def finish(self,p,receipt,*,now):
        r=observe_fixture(p,receipt)
        with closing(self.connect()) as db,db:
            cur=db.execute("UPDATE reservations SET state=?,updated=?,receipt=? WHERE event_id=? AND preview_hash=? AND state='reserved' AND updated<=?",
                          (r["state"],now,canonical(r),p["event_id"],digest(p),now))
            return cur.rowcount==1
    def recover(self,*,now,timeout=120):
        with closing(self.connect()) as db,db:
            return db.execute("UPDATE reservations SET state='unknown_requires_reconciliation',updated=? WHERE state='reserved' AND updated<=?",(now,now-timeout)).rowcount
