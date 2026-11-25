"""Prospective observation of frozen shadow packets using public reference candles."""
import argparse,json,sqlite3,time,hashlib
from datetime import datetime
from contextlib import closing
from pathlib import Path
from .reference_history import candles
from .backtest import outcome,STEP,HORIZONS
from .planner_shadow import VERSION
from tradebot.market_data_v3 import MARKETS

STRIDE=7200
COST=15.0
SCHEMA="forward-reference-v1"
def readonly(p):
    return sqlite3.connect(Path(p).resolve().as_uri()+"?mode=ro",uri=True,timeout=2)
def initialize(db,now):
    db.execute("CREATE TABLE IF NOT EXISTS protocol (id INTEGER PRIMARY KEY CHECK(id=1), start INTEGER NOT NULL, version TEXT NOT NULL)")
    db.execute("INSERT OR IGNORE INTO protocol VALUES(1,?,?)",(now,SCHEMA))
    start,version=db.execute("SELECT start,version FROM protocol WHERE id=1").fetchone()
    if version!=SCHEMA:raise ValueError("protocol mismatch")
    db.execute("""CREATE TABLE IF NOT EXISTS outcomes (
       symbol TEXT NOT NULL,bucket INTEGER NOT NULL,decision_at INTEGER NOT NULL,horizon_s INTEGER NOT NULL,
       side TEXT NOT NULL,packet_sha TEXT NOT NULL,packet TEXT NOT NULL,entry_at INTEGER NOT NULL,exit_at INTEGER NOT NULL,
       status TEXT NOT NULL,gross_bps REAL,net_bps REAL,
       PRIMARY KEY(symbol,bucket,horizon_s))""")
    return start

def enroll(db,symbol,packets,start,now):
    for raw in packets:
        p=json.loads(raw);at=p["as_of"];side=p["direction"]
        if p["symbol"]!=symbol or p["version"]!=VERSION or not start<=at<=now or side not in ("LONG","SHORT","NEUTRAL"):
            continue
        bucket=at//STRIDE
        # One earliest observed packet per bucket, even when neutral.
        if db.execute("SELECT 1 FROM outcomes WHERE symbol=? AND bucket=?",(symbol,bucket)).fetchone():continue
        entry=((at+STEP-1)//STEP)*STEP+STEP
        for h in HORIZONS:
            status="neutral" if side=="NEUTRAL" else "pending"
            if status=="pending" and db.execute("""SELECT 1 FROM outcomes WHERE symbol=? AND horizon_s=?
               AND status IN ('pending','observed','missing_reference') AND exit_at>? LIMIT 1""",(symbol,h,entry)).fetchone():
                status="overlap"
            db.execute("INSERT INTO outcomes VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
                (symbol,bucket,at,h,side,hashlib.sha256(raw.encode()).hexdigest(),raw,entry,entry+h,status))

def settle(db,symbol,bars,end):
    if not bars:return
    for bucket,h,side,entry,exit_at in db.execute(
        "SELECT bucket,horizon_s,side,entry_at,exit_at FROM outcomes WHERE symbol=? AND status='pending' AND exit_at+?<=?",(symbol,STEP,end)).fetchall():
        result=outcome(bars,entry-STEP,h,side,COST)
        status="observed" if result else "missing_reference"
        db.execute("UPDATE outcomes SET status=?,gross_bps=?,net_bps=? WHERE symbol=? AND bucket=? AND horizon_s=?",
            (status,result["gross_bps"] if result else None,result["net_bps"] if result else None,symbol,bucket,h))

def fill_counts(path,symbol,start):
    if not path.exists():return {"status":"unavailable"}
    count=flat=unknown=0
    with closing(readonly(path)) as db:
        for raw, in db.execute("SELECT detail FROM observed_fills WHERE symbol=?",(symbol,)):
            f=json.loads(raw)
            try:at=datetime.fromisoformat(f["created_at"].replace("Z","+00:00")).timestamp()
            except (ValueError,TypeError,KeyError,AttributeError):
                unknown+=1;continue
            if at<start:continue
            count+=1;flat+=int(f.get("position_flat_after_fill") is True)
    return {"status":"observed_fill_counts_only","fills":count,"flat_after_fill":flat,
            "unknown_timestamp":unknown,"realized_trade_pnl":None,"win_rate":None}

def run(root,symbol,now,fetch=candles):
    root=Path(root)/symbol
    with closing(sqlite3.connect(root/"forward_validation.sqlite",timeout=5)) as db:
        with db:start=initialize(db,now)
        source=root/"planner_shadow.sqlite"
        if source.exists():
            with closing(readonly(source)) as r:
                raw=[x[0] for x in r.execute("SELECT payload FROM planner_packets WHERE symbol=? AND version=? AND as_of>=? AND as_of<=? ORDER BY as_of",(symbol,VERSION,start,now))]
            with db:enroll(db,symbol,raw,start,now)
        end=now//STEP*STEP
        feed="not_due"
        if db.execute("SELECT 1 FROM outcomes WHERE status='pending' AND exit_at+?<=? LIMIT 1",(STEP,end)).fetchone():
            try:
                bars={r["time"]:r for r in fetch(symbol,"5m",end,250)}
                with db:settle(db,symbol,bars,end)
                feed="available"
            except Exception as exc:feed="unavailable:"+type(exc).__name__
        rows=[{"horizon_s":h,"status":status,"count":n,"mean_net_bps":avg,"wins":wins}
              for h,status,n,avg,wins in db.execute("""SELECT horizon_s,status,count(*),avg(net_bps),
                sum(CASE WHEN net_bps>0 THEN 1 ELSE 0 END) FROM outcomes GROUP BY horizon_s,status ORDER BY horizon_s,status""")]
        result={"version":SCHEMA,"symbol":symbol,"start":start,"generated":now,"stride_s":STRIDE,
                "assumed_cost_bps":COST,"reference_feed":feed,"outcomes":rows,
                "actual_demo":fill_counts(root/"orders.sqlite",symbol,start),
                "validation":"collecting_only","execution_effect":"none"}
    tmp=root/"forward_validation.tmp";tmp.write_text(json.dumps(result,allow_nan=False)+"\n");tmp.replace(root/"forward_validation.json")
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir",required=True);a=p.parse_args()
    failures=0
    for s in MARKETS:
        try:print(json.dumps(run(a.data_dir,s,int(time.time())),allow_nan=False),flush=True)
        except Exception as exc:
            failures+=1
            print(json.dumps({"symbol":s,"error":type(exc).__name__}),flush=True)
    return int(bool(failures))
if __name__=="__main__":raise SystemExit(main())
