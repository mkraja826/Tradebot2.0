"""Immutable trade outcome research; no execution, provider calls or network."""
import argparse,json,math,sqlite3,time
from pathlib import Path
from contextlib import closing
from collections import Counter
from .performance import dec,stamp,read_performance
from .decision_review import read_review
from .trade_excursion import report as excursions
VERSION="outcome-learning-v1"
STEP=300
HORIZONS=(900,3600,14400)

def connect(p):
    return sqlite3.connect(Path(p).resolve().as_uri()+"?mode=ro",uri=True,timeout=2)

def initialize(db):
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS lessons (symbol TEXT, decision_id TEXT, closed TEXT, enrolled INTEGER, payload TEXT NOT NULL, PRIMARY KEY(symbol,decision_id,closed))")
        db.execute("CREATE TABLE IF NOT EXISTS followups (symbol TEXT, decision_id TEXT, closed TEXT, horizon INTEGER, start INTEGER, finish INTEGER, status TEXT, timing TEXT, payload TEXT, PRIMARY KEY(symbol,decision_id,closed,horizon))")

def enroll(db,symbol,performance,review,excursion,now):
    if performance.get("status")!="reconciled_subset" or review.get("status")!="observed":return 0
    rows=review.get("recent",[]);xs=excursion.get("episodes",[])
    inserted=0
    for ep in performance.get("recent_episodes",[]):
        ident=ep.get("decision_id");t=stamp({"created_at":ep.get("closed")});opened=stamp({"created_at":ep.get("opened")})
        if ep.get("attribution")!="single_recover_entry_order" or not ident or t is None or opened is None or not opened<t or t.timestamp()>now or ep.get("direction") not in ("LONG","SHORT"):continue
        r=[x for x in rows if x.get("id")==ident and x.get("outcome")=="closed_reconciled"]
        n=dec(ep.get("net_before_funding"))
        if len(r)!=1 or n is None or dec(r[0].get("net_before_funding"))!=n:continue
        r=r[0];match=[x for x in xs if x.get("decision_id")==ident and x.get("closed")==ep["closed"] and x.get("opened")==ep["opened"]]
        x=match[0] if len(match)==1 else {}
        keys=("status","coverage","mfe_bps","mae_bps","weighted_exit_price","gross_weighted_exit_return_bps","observed_favorable_gap_bps")
        lesson={"version":VERSION,"symbol":symbol,"decision_id":ident,"opened":ep["opened"],"closed":ep["closed"],"direction":ep["direction"],"active_rules":ep.get("active_rules",[]),"net_before_funding":str(n),"gross_pnl":ep.get("gross_pnl"),"fees":ep.get("fees"),"outcome":"win" if n>0 else "loss" if n<0 else "breakeven",
            "entry_evidence":{k:r.get(k) for k in ("entry_deviation_bps","fill_stop_bps","fill_target_bps","planned_stop_bps","planned_target_bps")},
            "exit_evidence":{k:x.get(k) for k in keys},"hypothesis":"post_exit_direction_continuation_descriptive","learning_status":"observation_only","execution_effect":"none"}
        start=(int(t.timestamp())//STEP+1)*STEP
        with db:
            changed=db.execute("INSERT OR IGNORE INTO lessons VALUES (?,?,?,?,?)",(symbol,ident,ep["closed"],now,json.dumps(lesson,allow_nan=False))).rowcount
            if not changed:continue
            inserted+=1
            for h in HORIZONS:
                timing="prospective_window" if now<=start else "retrospective_window" if now>=start+h else "partly_elapsed_at_enrollment"
                db.execute("INSERT INTO followups VALUES (?,?,?,?,?,?,'pending',?,NULL)",(symbol,ident,ep["closed"],h,start,start+h,timing))
    return inserted

def measure(bars,start,finish,direction):
    if direction not in ("LONG","SHORT") or finish<=start or (finish-start)%STEP:return None
    rows=[]
    for t in range(start,finish,STEP):
        r=bars.get(t)
        if not isinstance(r,dict) or r.get("time")!=t:return None
        o,h,l,c=(dec(r.get(k)) for k in ("open","high","low","close"))
        if any(v is None for v in (o,h,l,c)) or not 0<l<=min(o,c)<=max(o,c)<=h:return None
        rows.append((o,h,l,c))
    sign=1 if direction=="LONG" else -1
    base=rows[0][0];last=rows[-1][3]
    return {"gross_directional_price_return_bps":float(sign*(last-base)/base*10000),"baseline_open":str(base),"final_close":str(last),"bars":len(rows),"basis":"same_demo_market_post_exit_full_candles_not_executable_pnl"}

def settle(db,symbol,bars,now):
    rows=db.execute("SELECT f.decision_id,f.closed,f.horizon,f.start,f.finish,l.payload FROM followups f JOIN lessons l USING(symbol,decision_id,closed) WHERE f.symbol=? AND f.status='pending' AND f.finish+?<=?",(symbol,STEP,now)).fetchall()
    for i,c,h,a,b,raw in rows:
        value=measure(bars,a,b,json.loads(raw)["direction"])
        status="observed" if value is not None else "missing_candles" if now>=b+86400 else "pending"
        if status!="pending":
            with db:db.execute("UPDATE followups SET status=?,payload=? WHERE symbol=? AND decision_id=? AND closed=? AND horizon=? AND status='pending'",(status,json.dumps(value,allow_nan=False),symbol,i,c,h))

def report(directory,symbol):
    out={"version":VERSION,"status":"journal_unavailable","execution_effect":"none","learning_status":"observation_only","lessons":[],"followups":[]}
    try:
        with closing(connect(Path(directory)/"learning.sqlite")) as db:
            out["lessons"]=[{**json.loads(r),"enrolled":t} for t,r in db.execute("SELECT enrolled,payload FROM lessons WHERE symbol=? ORDER BY closed DESC LIMIT 50",(symbol,))]
            out["followups"]=[{"decision_id":i,"closed":c,"horizon_s":h,"start":a,"finish":b,"status":s,"timing":t,"evidence":json.loads(r) if r else None} for i,c,h,a,b,s,t,r in db.execute("SELECT decision_id,closed,horizon,start,finish,status,timing,payload FROM followups WHERE symbol=? ORDER BY closed DESC,horizon LIMIT 150",(symbol,))]
            out.update(status="observed",lesson_count=db.execute("SELECT count(*) FROM lessons WHERE symbol=?",(symbol,)).fetchone()[0],followup_counts={s:n for s,n in db.execute("SELECT status,count(*) FROM followups WHERE symbol=? GROUP BY status",(symbol,))})
    except (sqlite3.Error,ValueError,TypeError,KeyError):pass
    return out

def run(data,directory,symbol,now):
    root=Path(data)/symbol
    with closing(sqlite3.connect(Path(directory)/"learning.sqlite",timeout=5)) as db:
        initialize(db)
        perf=read_performance(root,symbol);review=read_review(root,symbol,perf);x=excursions(root,symbol,perf)
        enroll(db,symbol,perf,review,x,now)
        with closing(connect(root/"market.sqlite")) as src:
            bars={t:json.loads(r) for t,r in src.execute("SELECT stamp,payload FROM samples WHERE symbol=? AND series='candle:5m' AND stamp<?",(symbol,now//STEP*STEP))}
        settle(db,symbol,bars,now)
    return report(directory,symbol)

def main():
    p=argparse.ArgumentParser();p.add_argument("--data-dir",required=True);p.add_argument("--directory",required=True);a=p.parse_args()
    failures=0
    for s in ("BTCUSD","XAUTUSD"):
        try:
            r=run(a.data_dir,a.directory,s,int(time.time()));print(json.dumps({"symbol":s,"status":r["status"],"lessons":r.get("lesson_count"),"followups":r.get("followup_counts")}),flush=True)
        except Exception as e:failures+=1;print(json.dumps({"symbol":s,"error":type(e).__name__}),flush=True)
    return int(bool(failures))
if __name__=="__main__":raise SystemExit(main())
