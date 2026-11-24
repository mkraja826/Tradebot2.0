"""Append-only public research observations, isolated by market and timeframe."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
from tradebot.market_data_v3 import MARKETS, FRAMES, normalize

class MarketStore:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.is_symlink(): raise ValueError("symlink_database")
        with closing(self.connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS samples(
              symbol TEXT NOT NULL, series TEXT NOT NULL, stamp INTEGER NOT NULL,
              payload TEXT NOT NULL, PRIMARY KEY(symbol,series,stamp))""")
    def connect(self):
        return sqlite3.connect(self.path,timeout=10)
    def _write(self,symbol,series,items):
        if symbol not in MARKETS: raise ValueError("invalid_symbol")
        inserted=0
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            for stamp,payload in items:
                raw=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False)
                old=db.execute("SELECT payload FROM samples WHERE symbol=? AND series=? AND stamp=?",
                               (symbol,series,stamp)).fetchone()
                if old:
                    if old[0]!=raw: raise ValueError("conflicting_observation")
                else:
                    db.execute("INSERT INTO samples VALUES(?,?,?,?)",(symbol,series,stamp,raw))
                    inserted+=1
        return inserted
    def candles(self,symbol,frame,bars,*,as_of):
        if frame not in FRAMES or not bars: raise ValueError("invalid_frame")
        rows=normalize(bars,frame,as_of=as_of,count=len(bars))
        return self._write(symbol,"candle:"+frame,[(x["time"],x) for x in rows])
    def derivative_history(self,kind,rows,*,as_of):
        from tradebot.derivative_context_v3 import normalize_series
        checked=normalize_series(rows,kind,as_of=as_of)
        return self._write("BTCUSD",kind,[(r["time"],r) for r in checked])
    def intelligence(self,symbol,kind,features):
        if kind not in ("ticker","book","flow","xau_reference") or features.get("source")!={"ticker":"delta_demo_ticker","book":"delta_demo_l2","flow":"delta_demo_recent_trade_sample","xau_reference":"gold_api_indicative_spot"}.get(kind):
            raise ValueError("invalid_intelligence")
        if kind=="xau_reference" and symbol!="XAUTUSD": raise ValueError("wrong_reference_market")
        stamp=features.get("timestamp_us")
        if type(stamp) is not int or stamp<=0: raise ValueError("invalid_timestamp")
        return self._write(symbol,kind,[(stamp,features)])
    def history(self,symbol,series,limit=250):
        if symbol not in MARKETS or series not in {"ticker","book","flow","xau_reference","funding:1h","mark:5m","index:5m",*("candle:"+f for f in FRAMES)} or type(limit) is not int or not 1<=limit<=10000:
            raise ValueError("invalid_query")
        with closing(self.connect()) as db:
            rows=db.execute("SELECT payload FROM samples WHERE symbol=? AND series=? ORDER BY stamp DESC LIMIT ?",(symbol,series,limit)).fetchall()
        return [json.loads(x[0]) for x in reversed(rows)]
    def counts(self):
        with closing(self.connect()) as db:
            return db.execute("SELECT symbol,series,count(*) FROM samples GROUP BY symbol,series ORDER BY symbol,series").fetchall()
