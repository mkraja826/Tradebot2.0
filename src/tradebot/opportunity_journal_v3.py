from tradebot.strategy_registry_v3 import valid_signal_rule
"""Persistent shadow opportunity journal. Never dispatch AI or place orders."""
from contextlib import closing
from pathlib import Path
import hashlib,json,sqlite3
from tradebot.market_data_v3 import MARKETS,FRAMES

ROUTE={"BTCUSD":"GPT-6.1 Sol","XAUTUSD":"DeepSeek"}
HISTORICAL_ROUTES={"BTCUSD":frozenset(("GPT-6","GPT-6.1 Sol")),"XAUTUSD":frozenset(("DeepSeek",))}
def known_route(symbol,route):
    return isinstance(route,str) and route in HISTORICAL_ROUTES.get(symbol,())

def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False)
def digest(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()

class OpportunityJournal:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with closing(self.connect()) as db,db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS events(
              event_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,as_of INTEGER NOT NULL,
              payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS seen(
              symbol TEXT NOT NULL,rule_id TEXT NOT NULL,frame TEXT NOT NULL,
              direction TEXT NOT NULL,closed_at INTEGER NOT NULL,event_id TEXT NOT NULL,
              PRIMARY KEY(symbol,rule_id,frame,direction,closed_at),
              FOREIGN KEY(event_id) REFERENCES events(event_id));
            """)
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute("PRAGMA foreign_keys=ON")
        return db
    def record(self,scan,context):
        symbol=scan["symbol"]; stamp=scan["as_of"]
        if symbol not in MARKETS or type(stamp) is not int or stamp<=0:
            raise ValueError("invalid_scan_identity")
        if scan.get("ai_dispatched") is not False or scan.get("orders_submitted")!=0:
            raise ValueError("shadow_only")
        if context.get("symbol")!=symbol or context.get("as_of")!=stamp:
            raise ValueError("context_identity_mismatch")
        signals={}
        for s in scan["signals"]:
            r,f,d,t=(s[k] for k in ("id","frame","direction","closed_at"))
            prefix="B" if symbol=="BTCUSD" else "G"
            if not valid_signal_rule(symbol,r,f) or f not in FRAMES or d not in ("LONG","SHORT") or type(t) is not int or t!=stamp//FRAMES[f]*FRAMES[f] or t<=0:
                raise ValueError("invalid_or_stale_signal")
            signals[(symbol,r,f,d,t)]=s
        with closing(self.connect()) as db,db:
            db.execute("BEGIN IMMEDIATE")
            new=[k for k in sorted(signals) if not db.execute(
                "SELECT 1 FROM seen WHERE symbol=? AND rule_id=? AND frame=? AND direction=? AND closed_at=?",k).fetchone()]
            if not new: return None
            event_id=digest(new)
            event={"event_id":event_id,"symbol":symbol,"as_of":stamp,"model_if_enabled":ROUTE[symbol],
                   "signal_rule":"one_of_n","new_signals":[signals[k] for k in new],
                   "all_signals":[signals[k] for k in sorted(signals)],
                   "conflicting_directions":len({k[3] for k in signals})>1,
                   "context":context,"context_sha256":digest(context),
                   "mode":"shadow","ai_dispatched":False,"orders_submitted":0,"execution_authorized":False}
            db.execute("INSERT INTO events VALUES(?,?,?,?)",(event_id,symbol,stamp,canonical(event)))
            db.executemany("INSERT INTO seen VALUES(?,?,?,?,?,?)",[(*k,event_id) for k in new])
            return event
    def counts(self):
        with closing(self.connect()) as db:
            return {s:{"events":db.execute("SELECT count(*) FROM events WHERE symbol=?",(s,)).fetchone()[0],
                       "signals":db.execute("SELECT count(*) FROM seen WHERE symbol=?",(s,)).fetchone()[0]} for s in MARKETS}
