"""Prospectively frozen comparison of original and overlap-adjusted consensus.

Local research only. No order, model, or network access.
"""
import argparse,json,sqlite3,time,hashlib
from pathlib import Path
from contextlib import closing
from statistics import mean
from .outcome_learning import connect,measure,STEP,HORIZONS
from .overlap_confidence import score,groups_for,LOOKBACK,BUCKET,VERSION as SCORE_VERSION
from .planner_shadow import VERSION as SOURCE_VERSION
VERSION="overlap-forward-v1"
STRIDE=3600
MAX_AGE=180
COST_BPS=15
SIDES=("LONG","SHORT","NEUTRAL")

def encode(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)

def initialize(db,now):
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS protocol(id INTEGER PRIMARY KEY CHECK(id=1),start INTEGER NOT NULL,version TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO protocol VALUES(1,?,?)",(now,VERSION))
        start,version=db.execute("SELECT start,version FROM protocol").fetchone()
        if version!=VERSION:raise ValueError("protocol mismatch")
        db.execute("""CREATE TABLE IF NOT EXISTS pairs(
            symbol TEXT NOT NULL,bucket INTEGER NOT NULL,horizon INTEGER NOT NULL,
            enrolled INTEGER NOT NULL,source_at INTEGER NOT NULL,entry_at INTEGER NOT NULL,exit_at INTEGER NOT NULL,
            baseline TEXT NOT NULL,alternative TEXT NOT NULL,packet TEXT NOT NULL,
            status TEXT NOT NULL,baseline_net REAL,alternative_net REAL,
            PRIMARY KEY(symbol,bucket,horizon))""")
    return start

def enroll(db,symbol,p,prior,start,now):
    at=p.get("as_of")
    if groups_for(symbol,p) is None or not start<=at<=now or now-at>MAX_AGE:return False
    bucket=now//STRIDE
    if db.execute("SELECT 1 FROM pairs WHERE symbol=? AND (bucket=? OR source_at=?)",(symbol,bucket,at)).fetchone():return False
    # History was actually read before enrollment. Exclude the current five-minute bucket.
    history=[x for x in prior if groups_for(symbol,x) is not None and at//BUCKET-LOOKBACK<=x["as_of"]//BUCKET<at//BUCKET]
    result=score(symbol,p,history)
    if result["status"]!="observed":return False
    a,b=result["baseline_direction"],result["research_direction"]
    if a not in SIDES or b not in SIDES:return False
    # Extra full candle of lead time between enrollment and the measurement window.
    entry=(now//STEP+2)*STEP
    packet={"version":VERSION,"score_version":SCORE_VERSION,"source":p,"score":result,
        "prior_packet_count":len(history),"prior_sha256":hashlib.sha256(encode(sorted(history,key=lambda x:x["as_of"])).encode()).hexdigest(),
        "enrolled":now,"entry_at":entry}
    raw=encode(packet)
    with db:
        for h in HORIZONS:
            overlapping=db.execute("SELECT 1 FROM pairs WHERE symbol=? AND horizon=? AND status!='overlap' AND exit_at>?",(symbol,h,entry)).fetchone()
            db.execute("INSERT INTO pairs VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)",(symbol,bucket,h,now,at,entry,entry+h,a,b,raw,"overlap" if overlapping else "pending"))
    return True

def settle(db,symbol,bars,now):
    rows=db.execute("SELECT bucket,horizon,entry_at,exit_at,baseline,alternative FROM pairs WHERE symbol=? AND status='pending' AND exit_at+?<=?",(symbol,STEP,now)).fetchall()
    for bucket,h,a,b,base,alt in rows:
        r=measure(bars,a,b,"LONG")
        if r is None:
            if now>=b+86400:
                with db:db.execute("UPDATE pairs SET status='missing_candles' WHERE symbol=? AND bucket=? AND horizon=? AND status='pending'",(symbol,bucket,h))
            continue
        gross=r["gross_directional_price_return_bps"]
        def net(side):return 0.0 if side=="NEUTRAL" else (gross if side=="LONG" else -gross)-COST_BPS
        with db:db.execute("UPDATE pairs SET status='observed',baseline_net=?,alternative_net=? WHERE symbol=? AND bucket=? AND horizon=? AND status='pending'",(net(base),net(alt),symbol,bucket,h))

def summarize(rows):
    diffs=[a-b for _,_,b,a in rows];changed=[a-b for x,y,b,a in rows if x!=y]
    return {"observed_pairs":len(rows),"disagreements":len(changed),"mean_baseline_net_bps":mean(r[2] for r in rows) if rows else None,
        "mean_alternative_net_bps":mean(r[3] for r in rows) if rows else None,"mean_difference_bps":mean(diffs) if diffs else None,
        "disagreement_mean_difference_bps":mean(changed) if changed else None,"alternative_better":sum(x>0 for x in diffs),"baseline_better":sum(x<0 for x in diffs),"ties":sum(x==0 for x in diffs),
        "baseline_directional_windows":sum(x!="NEUTRAL" for x,y,b,a in rows),"alternative_directional_windows":sum(y!="NEUTRAL" for x,y,b,a in rows)}

def report(directory,symbol):
    out={"version":VERSION,"symbol":symbol,"status":"journal_unavailable","execution_effect":"none","validation":"collecting_only","additional_ai_calls":0,"horizons":[],"latest":None}
    try:
        with closing(connect(Path(directory)/"overlap_forward.sqlite")) as db:
            start,version=db.execute("SELECT start,version FROM protocol").fetchone()
            if version!=VERSION:return out
            out.update(status="observed",protocol_start=start,assumed_cost_bps=COST_BPS,stride_s=STRIDE)
            for h in HORIZONS:
                counts=dict(db.execute("SELECT status,count(*) FROM pairs WHERE symbol=? AND horizon=? GROUP BY status",(symbol,h)))
                rows=db.execute("SELECT baseline,alternative,baseline_net,alternative_net FROM pairs WHERE symbol=? AND horizon=? AND status='observed'",(symbol,h)).fetchall()
                out["horizons"].append({"horizon_s":h,"counts":counts,**summarize(rows)})
            row=db.execute("SELECT packet FROM pairs WHERE symbol=? ORDER BY enrolled DESC LIMIT 1",(symbol,)).fetchone()
            if row:
                p=json.loads(row[0]);out["latest"]={"enrolled":p["enrolled"],"entry_at":p["entry_at"],"source_at":p["source"]["as_of"],"score":p["score"]}
    except (sqlite3.Error,ValueError,TypeError,KeyError):pass
    return out

def run(data,directory,symbol,now):
    root=Path(data)/symbol
    with closing(sqlite3.connect(Path(directory)/"overlap_forward.sqlite",timeout=5)) as db:
        start=initialize(db,now)
        with closing(connect(root/"planner_shadow.sqlite")) as src:
            packets=[json.loads(r) for r, in src.execute("SELECT payload FROM planner_packets WHERE symbol=? AND version=? AND as_of>=? AND as_of<=? ORDER BY as_of",(symbol,SOURCE_VERSION,now-(LOOKBACK+2)*BUCKET,now))]
        # Choose earliest available fresh packet; no selection by direction or return.
        for p in packets:
            if enroll(db,symbol,p,packets,start,now):break
        with closing(connect(root/"market.sqlite")) as src:
            bars={t:json.loads(r) for t,r in src.execute("SELECT stamp,payload FROM samples WHERE symbol=? AND series='candle:5m' AND stamp<?",(symbol,now//STEP*STEP))}
        settle(db,symbol,bars,now)
    return report(directory,symbol)

def main():
    p=argparse.ArgumentParser();p.add_argument("--data-dir",required=True);p.add_argument("--directory",required=True);a=p.parse_args();errors=0
    for s in ("BTCUSD","XAUTUSD"):
        try:
            r=run(a.data_dir,a.directory,s,int(time.time()));print(encode({"symbol":s,"status":r["status"],"horizons":r["horizons"]}),flush=True)
        except Exception as e:errors+=1;print(encode({"symbol":s,"error":type(e).__name__}),flush=True)
    return int(bool(errors))
if __name__=="__main__":raise SystemExit(main())
