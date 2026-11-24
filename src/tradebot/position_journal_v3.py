"""Durable M8 observations; flat is not proof of a fill or settlement."""
import sqlite3,json
from pathlib import Path
from contextlib import closing
from tradebot.position_observer_v3 import structural
from tradebot.opportunity_journal_v3 import canonical,digest
from tradebot.market_data_v3 import MARKETS

class PositionJournal:
    def __init__(self,path):
        self.path=Path(path)
        with closing(self.connect()) as db,db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS latest(symbol TEXT PRIMARY KEY,observed_us INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS changes(symbol TEXT NOT NULL,observed_us INTEGER NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(symbol,observed_us));
            """)
    def connect(self): return sqlite3.connect(self.path,timeout=10)
    def record(self,v):
        s=v["symbol"]
        if s not in MARKETS: raise ValueError("unknown_symbol")
        if v["status"]=="unknown": return "unknown_not_recorded"
        t=v["observed_us"]
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            r=db.execute("SELECT observed_us,payload FROM latest WHERE symbol=?",(s,)).fetchone()
            previous=json.loads(r[1]) if r else None
            if r and t<=r[0]:
                if t==r[0] and digest(v)!=digest(previous): return "conflicting_observation"
                return "duplicate_or_older"
            kind=None
            if previous is None: kind="initial_observation"
            elif structural(v)!=structural(previous):
                before,after=bool(previous["positions"]),bool(v["positions"])
                kind="position_appeared" if not before and after else "position_disappeared_unsettled" if before and not after else "inventory_or_protection_changed"
            if kind:
                payload={"previous":structural(previous) if previous else None,"current":structural(v),"settlement_verified":False}
                db.execute("INSERT INTO changes VALUES(?,?,?,?)",(s,t,kind,canonical(payload)))
            db.execute("INSERT INTO latest VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET observed_us=excluded.observed_us,payload=excluded.payload",(s,t,canonical(v)))
            return kind or "unchanged"
    def last(self,symbol):
        with closing(self.connect()) as db:
            r=db.execute("SELECT payload FROM latest WHERE symbol=?",(symbol,)).fetchone()
            return json.loads(r[0]) if r else None
    def counts(self):
        with closing(self.connect()) as db:
            return {s:db.execute("SELECT count(*) FROM changes WHERE symbol=?",(s,)).fetchone()[0] for s in MARKETS}
