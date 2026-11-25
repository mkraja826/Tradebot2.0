"""Prospective mark-price signal research, independent of AI and exchange orders."""
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from .regime import FAMILIES

HORIZONS=(900,3600,14400)
TOLERANCE=300

class SignalResearch:
    def __init__(self,path):
        self.path=Path(path)
        with closing(sqlite3.connect(self.path,timeout=10)) as db,db:
            db.execute("""CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY, symbol TEXT NOT NULL, rule_id TEXT NOT NULL,
                family TEXT NOT NULL, frame TEXT NOT NULL, side TEXT NOT NULL,
                regime TEXT NOT NULL, volatility TEXT NOT NULL, closed_at INTEGER NOT NULL,
                entry_us INTEGER NOT NULL, entry REAL NOT NULL, horizon_s INTEGER NOT NULL,
                status TEXT NOT NULL, exit_us INTEGER, exit REAL, return_bps REAL)""")
            db.execute("CREATE INDEX IF NOT EXISTS research_pending ON observations(symbol,status,entry_us)")
    def record(self,report,direction):
        symbol=report["symbol"]; as_of=report["as_of"]
        quote=(report.get("market_context",{}).get("quotes",{}).get("ticker") or {})
        stamp=quote.get("timestamp_us")
        try: mark=float(quote.get("mark"))
        except (ValueError,TypeError): return {"status":"quote_unavailable"}
        if (type(stamp) is not int or not 0<=as_of*1000000-stamp<=120000000
                or not math.isfinite(mark) or mark<=0):
            return {"status":"quote_unavailable"}
        inserted=observed=missed=0
        with closing(sqlite3.connect(self.path,timeout=10)) as db,db:
            db.execute("BEGIN IMMEDIATE")
            for ident,side,entry,entry_us,horizon in db.execute(
                """SELECT id,side,entry,entry_us,horizon_s FROM observations
                   WHERE symbol=? AND status='pending' AND entry_us+horizon_s*1000000<=?""",(symbol,stamp)).fetchall():
                lag=(stamp-entry_us)/1000000-horizon
                if lag>TOLERANCE:
                    db.execute("UPDATE observations SET status='missed' WHERE id=?",(ident,))
                    missed+=1
                else:
                    bps=(mark/entry-1)*10000*(1 if side=="LONG" else -1)
                    db.execute("UPDATE observations SET status='observed',exit_us=?,exit=?,return_bps=? WHERE id=?",
                               (stamp,mark,bps,ident)); observed+=1
            # Deduplicate across repeated scans/restarts and across AI retries.
            for signal in report.get("signals",[]):
                if stamp<signal["closed_at"]*1000000:
                    continue
                for horizon in HORIZONS:
                    ident=hashlib.sha256(json.dumps([symbol,signal["id"],signal["frame"],signal["direction"],signal["closed_at"],horizon]).encode()).hexdigest()
                    row=db.execute("""INSERT OR IGNORE INTO observations VALUES
                        (?,?,?,?,?,?,?,?,?,?,?,?,'pending',NULL,NULL,NULL)""",
                        (ident,symbol,signal["id"],FAMILIES[signal["id"]],signal["frame"],signal["direction"],
                         direction["regime"]["regime"],direction["regime"]["volatility"],signal["closed_at"],stamp,mark,horizon))
                    inserted+=row.rowcount
        return {"status":"ok","new_horizon_samples":inserted,"observed":observed,"missed":missed}
