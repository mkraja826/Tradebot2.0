"""M7 shadow dispatch state machine. No provider transport or order authority."""
from contextlib import closing
from pathlib import Path
import sqlite3,json
from tradebot.opportunity_journal_v3 import canonical,digest,ROUTE

class DispatchJournal:
    def __init__(self,path):
        self.path=Path(path)
        with closing(self.connect()) as db,db:
            db.execute("""CREATE TABLE IF NOT EXISTS dispatch(
                event_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,as_of INTEGER NOT NULL,
                state TEXT NOT NULL,updated INTEGER NOT NULL,detail TEXT NOT NULL)""")
    def connect(self):
        return sqlite3.connect(self.path,timeout=10)
    def stage(self,event,*,now):
        key=event["event_id"]; s=event["symbol"]; stamp=event["as_of"]
        if s not in ROUTE or event.get("mode")!="shadow" or event.get("execution_authorized") is not False:
            raise ValueError("shadow_event_required")
        if event["context"].get("symbol")!=s or event["context"].get("as_of")!=stamp or digest(event["context"])!=event["context_sha256"]:
            raise ValueError("context_mismatch")
        if type(now) is not int or type(stamp) is not int or not 0<stamp<=now:
            raise ValueError("invalid_time")
        state="expired" if now-stamp>150 else "preview_pending"
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT symbol,as_of,state FROM dispatch WHERE event_id=?",(key,)).fetchone()
            if row:
                if row[:2]!=(s,stamp): raise ValueError("event_identity_collision")
                return row[2]
            db.execute("INSERT INTO dispatch VALUES(?,?,?,?,?,?)",(key,s,stamp,state,now,"shadow_only"))
        return state
    def claim_preview(self,key,*,now):
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT as_of,state,updated FROM dispatch WHERE event_id=?",(key,)).fetchone()
            if not row or row[1]!="preview_pending" or now<row[2]: return False
            state="expired" if now-row[0]>150 else "preview_reserved"
            db.execute("UPDATE dispatch SET state=?,updated=? WHERE event_id=?",(state,now,key))
            return state=="preview_reserved"
    def finish_preview(self,key,state,*,now):
        if state not in ("synthetic_completed","blocked_account","preview_failed","preview_unknown"):
            raise ValueError("invalid_shadow_result")
        with closing(self.connect()) as db,db:
            cur=db.execute("UPDATE dispatch SET state=?,updated=? WHERE event_id=? AND state='preview_reserved' AND updated<=?",(state,now,key,now))
            return cur.rowcount==1
    def recover(self,*,now,timeout=120):
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            a=db.execute("UPDATE dispatch SET state='preview_unknown',updated=? WHERE state='preview_reserved' AND updated<=?",(now,now-timeout)).rowcount
            b=db.execute("UPDATE dispatch SET state='expired',updated=? WHERE state='preview_pending' AND as_of<?",(now,now-150)).rowcount
            return {"unknown":a,"expired":b}
    def counts(self):
        with closing(self.connect()) as db:
            return db.execute("SELECT symbol,state,count(*) FROM dispatch GROUP BY symbol,state ORDER BY symbol,state").fetchall()
