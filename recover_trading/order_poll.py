"""Durable read-only lookup scheduling; never changes trade admission or replays orders."""
import json
from collections import defaultdict
VERSION="order-poll-v1"
HISTORICAL_INTERVAL=3600
HISTORICAL_BATCH=3
FRESH_BATCH=25

def missing(detail):
    return detail.get("http_status")==400 and detail.get("exchange_code")=="order_not_found"

class Schedule:
    def __init__(self,db):
        self.db=db
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS order_poll_schedule (client_id TEXT PRIMARY KEY,last_checked INTEGER NOT NULL,missing_streak INTEGER NOT NULL,first_missing INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS order_poll_seed (symbol TEXT PRIMARY KEY)")
    def seed(self,symbol):
        if self.db.execute("SELECT 1 FROM order_poll_seed WHERE symbol=?",(symbol,)).fetchone():return
        ids={i for i, in self.db.execute("SELECT client_id FROM orders WHERE symbol=? AND status IN ('unknown','submitting')",(symbol,))}
        histories=defaultdict(dict)
        for at,raw in self.db.execute("SELECT observed,detail FROM lifecycle_snapshots WHERE symbol=? ORDER BY id DESC LIMIT 200",(symbol,)):
            for ident,d in json.loads(raw).get("order_lookup_diagnostics",{}).items():
                if ident in ids:histories[ident].setdefault(at,d)
        with self.db:
            for ident,checks in histories.items():
                streak=0;first=0
                for at,d in sorted(checks.items()):
                    if missing(d):
                        if not streak:first=at
                        streak+=1
                    else:streak=first=0
                self.db.execute("INSERT OR IGNORE INTO order_poll_schedule VALUES (?,?,?,?)",(ident,max(checks),streak,first))
            self.db.execute("INSERT OR IGNORE INTO order_poll_seed VALUES (?)",(symbol,))
    def select(self,pending,now):
        fast=[];slow=[];deferred=0
        for ident,status,intent in pending:
            row=self.db.execute("SELECT last_checked,missing_streak,first_missing FROM order_poll_schedule WHERE client_id=?",(ident,)).fetchone()
            last,streak,first=row or (0,0,0)
            historical=status=="unknown" and streak>=3 and last-first>=120 and 0<=now-last
            if historical:
                if now-last>=HISTORICAL_INTERVAL:slow.append((last,ident,status,intent))
                else:deferred+=1
            else:fast.append((last,ident,status,intent))
        fast.sort(key=lambda r:(r[0],r[1]));slow.sort(key=lambda r:(r[0],r[1]))
        selected=fast[:FRESH_BATCH]+slow[:HISTORICAL_BATCH]
        return [(i,s,a) for _,i,s,a in selected],{"version":VERSION,"fresh_due":len(fast),"historical_due":len(slow),"historical_deferred":deferred,"fresh_selected":min(len(fast),FRESH_BATCH),"historical_selected":min(len(slow),HISTORICAL_BATCH),"due_remaining":max(0,len(fast)-FRESH_BATCH)+max(0,len(slow)-HISTORICAL_BATCH),"historical_interval_s":HISTORICAL_INTERVAL}
    def record(self,ident,now,detail):
        old=self.db.execute("SELECT last_checked,missing_streak,first_missing FROM order_poll_schedule WHERE client_id=?",(ident,)).fetchone()
        if missing(detail):
            last,n,first=old or (0,0,0)
            n,first=(n+int(now>last),first) if n and now>=last else (1,now)
        else:n=first=0
        with self.db:self.db.execute("INSERT OR REPLACE INTO order_poll_schedule VALUES (?,?,?,?)",(ident,now,n,first))
