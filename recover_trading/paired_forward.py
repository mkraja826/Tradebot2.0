"""Prospective paired comparison of candle-only consensus; no execution access."""
import argparse,hashlib,json,sqlite3,time
from pathlib import Path
from contextlib import closing
from statistics import mean
from .backtest import outcome,STEP,HORIZONS
from .reference_history import candles
from .reference_strategy import VERSION as SOURCE_VERSION
from tradebot.market_data_v3 import MARKETS

VERSION="paired-forward-v1"
STRIDE=7200
COST=15.0
MAX_REPORT_AGE=1200
SIDES=("LONG","SHORT","NEUTRAL")

def initialize(db,now):
    db.execute("CREATE TABLE IF NOT EXISTS protocol(id INTEGER PRIMARY KEY CHECK(id=1),start INTEGER NOT NULL,version TEXT NOT NULL)")
    db.execute("INSERT OR IGNORE INTO protocol VALUES(1,?,?)",(now,VERSION))
    start,version=db.execute("SELECT start,version FROM protocol WHERE id=1").fetchone()
    if version!=VERSION:raise ValueError("protocol mismatch")
    db.execute("""CREATE TABLE IF NOT EXISTS pairs(
        symbol TEXT NOT NULL,bucket INTEGER NOT NULL,horizon INTEGER NOT NULL,
        enrolled INTEGER NOT NULL,generated INTEGER NOT NULL,cutoff INTEGER NOT NULL,
        packet_sha TEXT NOT NULL,packet TEXT NOT NULL,demo_side TEXT,reference_side TEXT,
        entry_at INTEGER NOT NULL,exit_at INTEGER NOT NULL,status TEXT NOT NULL,
        demo_net REAL,reference_net REAL,
        PRIMARY KEY(symbol,bucket,horizon))""")
    return start

def enroll(db,symbol,raw,start,now):
    p=json.loads(raw)
    generated=p.get("generated");completed=p.get("completed");cutoff=p.get("as_of")
    if p.get("symbol")!=symbol or p.get("version")!=SOURCE_VERSION or not all(type(x) is int for x in (generated,completed,cutoff)):
        return False
    if not start<=generated<=completed<=now or not 0<cutoff<=generated or cutoff%STEP:
        return False
    if now-generated>MAX_REPORT_AGE or generated//STRIDE!=now//STRIDE:
        return False
    bucket=now//STRIDE
    if db.execute("SELECT 1 FROM pairs WHERE symbol=? AND bucket=?",(symbol,bucket)).fetchone():return False
    def side(key):
        v=p.get(key)
        return v.get("direction") if isinstance(v,dict) and v.get("direction") in SIDES else None
    demo,reference=side("matched_demo"),side("matched_reference")
    if type(p.get("comparable_rule_frames")) is not int or p["comparable_rule_frames"]<=0:
        demo=reference=None
    # Entry is based on first actual enrollment, not an older candle timestamp.
    entry=((now+STEP-1)//STEP)*STEP+STEP
    for h in HORIZONS:
        status="pending" if demo and reference else "unavailable_consensus"
        if status=="pending" and db.execute("""SELECT 1 FROM pairs WHERE symbol=? AND horizon=?
            AND status IN ('pending','observed','missing_reference') AND exit_at>? LIMIT 1""",(symbol,h,entry)).fetchone():
            status="overlap"
        db.execute("INSERT INTO pairs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
            (symbol,bucket,h,now,generated,cutoff,hashlib.sha256(raw.encode()).hexdigest(),raw,demo,reference,entry,entry+h,status))
    return True

def settle(db,symbol,bars,end):
    for bucket,h,entry,d,r in db.execute("""SELECT bucket,horizon,entry_at,demo_side,reference_side
        FROM pairs WHERE symbol=? AND status='pending' AND exit_at+?<=?""",(symbol,STEP,end)).fetchall():
        base=outcome(bars,entry-STEP,h,"LONG",0)
        if base is None:
            db.execute("UPDATE pairs SET status='missing_reference' WHERE symbol=? AND bucket=? AND horizon=?",(symbol,bucket,h))
            continue
        gross=base["gross_bps"]
        def net(side):return 0.0 if side=="NEUTRAL" else (gross if side=="LONG" else -gross)-COST
        db.execute("UPDATE pairs SET status='observed',demo_net=?,reference_net=? WHERE symbol=? AND bucket=? AND horizon=?",
            (net(d),net(r),symbol,bucket,h))

def summarize(rows):
    n=len(rows)
    out={"paired_windows":n,"mean_demo_net_bps_per_window":None,"mean_reference_net_bps_per_window":None,
         "mean_reference_minus_demo_bps":None,"reference_better":0,"demo_better":0,"ties":0}
    if n:
        out.update(mean_demo_net_bps_per_window=mean(x[2] for x in rows),
            mean_reference_net_bps_per_window=mean(x[3] for x in rows),
            mean_reference_minus_demo_bps=mean(x[3]-x[2] for x in rows),
            reference_better=sum(x[3]>x[2] for x in rows),demo_better=sum(x[2]>x[3] for x in rows),
            ties=sum(x[2]==x[3] for x in rows))
    for label,sideidx,netidx in (("demo",0,2),("reference",1,3)):
        entered=[x[netidx] for x in rows if x[sideidx]!="NEUTRAL"]
        out[label+"_entries"]=len(entered)
        out[label+"_mean_net_bps_per_entry"]=mean(entered) if entered else None
        out[label+"_win_rate_per_entry"]=sum(x>0 for x in entered)/len(entered) if entered else None
    return out

def run(root,symbol,now,fetch=candles):
    if symbol not in MARKETS or type(now) is not int:raise ValueError("invalid market")
    root=Path(root)/symbol
    with closing(sqlite3.connect(root/"paired_forward.sqlite",timeout=5)) as db:
        with db:start=initialize(db,now)
        source=root/"reference_strategy.sqlite"
        if source.exists():
            with closing(sqlite3.connect(source.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as src:
                candidates=src.execute("SELECT payload FROM comparisons WHERE symbol=? AND generated>=? AND generated<=? ORDER BY generated",
                    (symbol,max(start,now-MAX_REPORT_AGE,now//STRIDE*STRIDE),now)).fetchall()
            with db:
                for raw, in candidates:
                    if enroll(db,symbol,raw,start,now):break
        end=now//STEP*STEP
        feed="not_due"
        if db.execute("SELECT 1 FROM pairs WHERE symbol=? AND status='pending' AND exit_at+?<=? LIMIT 1",(symbol,STEP,end)).fetchone():
            try:
                bars={r["time"]:r for r in fetch(symbol,"5m",end,250)}
                with db:settle(db,symbol,bars,end)
                feed="available"
            except Exception as exc:feed="unavailable:"+type(exc).__name__
        horizons=[]
        for h in HORIZONS:
            counts=dict(db.execute("SELECT status,count(*) FROM pairs WHERE symbol=? AND horizon=? GROUP BY status",(symbol,h)))
            rows=db.execute("SELECT demo_side,reference_side,demo_net,reference_net FROM pairs WHERE symbol=? AND horizon=? AND status='observed'",(symbol,h)).fetchall()
            horizons.append({"horizon_s":h,"counts":counts,**summarize(rows),
                "disagreement_only":summarize([x for x in rows if x[0]!=x[1]])})
        latest=db.execute("SELECT enrolled,generated,cutoff,demo_side,reference_side,entry_at FROM pairs WHERE symbol=? ORDER BY bucket DESC LIMIT 1",(symbol,)).fetchone()
        result={"version":VERSION,"symbol":symbol,"start":start,"generated":now,"stride_s":STRIDE,
            "assumed_cost_bps":COST,"reference_feed":feed,"horizons":horizons,
            "latest_pair":dict(zip(("enrolled","source_generated","cutoff","demo_side","reference_side","entry_at"),latest)) if latest else None,
            "execution_effect":"none","validation":"collecting_only",
            "limitations":["First eligible comparison observed per UTC two-hour bucket after protocol start.",
             "Entry follows enrollment, not the original candle timestamp; nonoverlap per horizon.",
             "Both hypotheses use the same public reference open-to-open return; neutral is zero, costs only on entries.",
             "Disagreement results and participation reported separately. Not actual trades or AI comparison.",
             "No funding, slippage, leverage or liquidation simulation; 15 bps assumed costs."]}
    tmp=root/"paired_forward.tmp";tmp.write_text(json.dumps(result,allow_nan=False)+"\n");tmp.replace(root/"paired_forward.json")
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--data-dir",required=True);a=p.parse_args()
    failures=0
    for symbol in MARKETS:
        try:print(json.dumps(run(a.data_dir,symbol,int(time.time())),allow_nan=False),flush=True)
        except Exception as exc:
            failures+=1;print(json.dumps({"symbol":symbol,"error":type(exc).__name__}),flush=True)
    return int(bool(failures))
if __name__=="__main__":raise SystemExit(main())
