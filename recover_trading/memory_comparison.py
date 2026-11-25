"""Prospective comparison of actual AI entry proposals and a deterministic memory proxy.

No provider requests, order submissions or changes to trading state.
"""
import argparse,json,sqlite3,time,hashlib
from pathlib import Path
from contextlib import closing
from statistics import mean
from .performance import dec,stamp
from .outcome_learning import connect,measure,STEP,HORIZONS
VERSION="memory-comparison-v1"
STRIDE=3600
MAX_AGE=900
COST_BPS=15
MIN_EXPERIENCES=3

def encode(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)

def initialize(db,now):
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS protocol(id INTEGER PRIMARY KEY CHECK(id=1),start INTEGER NOT NULL,version TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO protocol VALUES(1,?,?)",(now,VERSION))
        start,version=db.execute("SELECT start,version FROM protocol").fetchone()
        if version!=VERSION:raise ValueError("protocol mismatch")
        db.execute("""CREATE TABLE IF NOT EXISTS pairs(symbol TEXT,bucket INTEGER,horizon INTEGER,decision_id TEXT,enrolled INTEGER,start INTEGER,finish INTEGER,baseline TEXT,alternative TEXT,packet TEXT,status TEXT,baseline_net REAL,alternative_net REAL,PRIMARY KEY(symbol,bucket,horizon))""")
    return start

def prior_experience(symbol,side,rules,cutoff,lessons):
    matched=[];seen=set()
    if not rules:return matched
    for enrolled,r in lessons:
        t=stamp({"created_at":r.get("closed")})
        n=dec(r.get("net_before_funding"));i=r.get("decision_id")
        if (r.get("symbol")!=symbol or r.get("direction")!=side or not i or i in seen or
            type(enrolled) is not int or not enrolled<cutoff or t is None or not t.timestamp()<=enrolled or
            n is None or sorted(set(r.get("active_rules",[])))!=rules):continue
        seen.add(i)
        matched.append({"decision_id":i,"closed":r["closed"],"enrolled":enrolled,"outcome":"win" if n>0 else "loss" if n<0 else "breakeven"})
    return matched

def enroll(db,symbol,decision,lessons,start,now):
    ident,created,context,result=decision
    at=context.get("as_of")
    side={"buy":"LONG","sell":"SHORT"}.get(result.get("side"))
    if (context.get("symbol")!=symbol or result.get("action")!="trade" or not side or
        type(created) is not int or type(at) is not int or not start<=at<=created+1 or
        not start<=created<=now or now-created>MAX_AGE or now-at>MAX_AGE):return False
    bucket=now//STRIDE
    if db.execute("SELECT 1 FROM pairs WHERE symbol=? AND (bucket=? OR decision_id=?)",(symbol,bucket,ident)).fetchone():return False
    rules=sorted({r["id"] for r in context.get("new_signals",[]) if isinstance(r,dict) and isinstance(r.get("id"),str)})
    experience=prior_experience(symbol,side,rules,min(at,created),lessons)
    # Hypothesis only: compare the same proposal with a neutral research
    # counterfactual after repeated net-negative outcomes of the same rule set.
    # Never applies to the running trader.
    losses=sum(r["outcome"]=="loss" for r in experience)
    alternative="NEUTRAL" if len(experience)>=MIN_EXPERIENCES and losses>len(experience)/2 else side
    reason="loss_majority_proxy" if alternative!=side else "insufficient_exact_experience" if len(experience)<MIN_EXPERIENCES else "no_loss_majority"
    packet={"version":VERSION,"decision_id":ident,"created":created,"as_of":at,"enrolled":now,"rules":rules,"baseline":side,"alternative":alternative,"experience":experience,"reason":reason,
        "source_context_sha256":hashlib.sha256(encode(context).encode()).hexdigest()}
    entry=(now//STEP+1)*STEP
    with db:
        for h in HORIZONS:
            overlapping=db.execute("SELECT 1 FROM pairs WHERE symbol=? AND horizon=? AND status!='overlap' AND finish>?",(symbol,h,entry)).fetchone()
            db.execute("INSERT INTO pairs VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)",(symbol,bucket,h,ident,now,entry,entry+h,side,alternative,encode(packet),"overlap" if overlapping else "pending"))
    return True

def settle(db,symbol,bars,now):
    for bucket,h,a,b,side,alt in db.execute("SELECT bucket,horizon,start,finish,baseline,alternative FROM pairs WHERE symbol=? AND status='pending' AND finish+?<=?",(symbol,STEP,now)).fetchall():
        r=measure(bars,a,b,side)
        if r is None:
            if now>=b+86400:
                with db:db.execute("UPDATE pairs SET status='missing_candles' WHERE symbol=? AND bucket=? AND horizon=?",(symbol,bucket,h))
            continue
        net=r["gross_directional_price_return_bps"]-COST_BPS
        with db:db.execute("UPDATE pairs SET status='observed',baseline_net=?,alternative_net=? WHERE symbol=? AND bucket=? AND horizon=?",(net,net if alt==side else 0.0,symbol,bucket,h))

def report(directory,symbol):
    out={"version":VERSION,"status":"journal_unavailable","execution_effect":"none","additional_ai_calls":0,"validation":"collecting_only","horizons":[],"latest":None}
    try:
        with closing(connect(Path(directory)/"comparison.sqlite")) as db:
            start,version=db.execute("SELECT start,version FROM protocol").fetchone()
            if version!=VERSION:return out
            out.update(status="observed",protocol_start=start,assumed_cost_bps=COST_BPS,minimum_exact_experiences=MIN_EXPERIENCES)
            for h in HORIZONS:
                counts=dict(db.execute("SELECT status,count(*) FROM pairs WHERE symbol=? AND horizon=? GROUP BY status",(symbol,h)))
                rows=db.execute("SELECT baseline,alternative,baseline_net,alternative_net FROM pairs WHERE symbol=? AND horizon=? AND status='observed'",(symbol,h)).fetchall()
                diffs=[a-b for _,_,b,a in rows];different=[a-b for x,y,b,a in rows if x!=y]
                out["horizons"].append({"horizon_s":h,"counts":counts,"observed_pairs":len(rows),"disagreements":len(different),"mean_baseline_net_bps":mean(r[2] for r in rows) if rows else None,"mean_alternative_net_bps":mean(r[3] for r in rows) if rows else None,"mean_difference_bps":mean(diffs) if diffs else None,"disagreement_mean_difference_bps":mean(different) if different else None,"alternative_better":sum(x>0 for x in diffs),"baseline_better":sum(x<0 for x in diffs),"ties":sum(x==0 for x in diffs)})
            row=db.execute("SELECT packet FROM pairs WHERE symbol=? ORDER BY enrolled DESC LIMIT 1",(symbol,)).fetchone()
            if row:out["latest"]=json.loads(row[0])
    except (sqlite3.Error,ValueError,TypeError):pass
    return out

def run(data,directory,learning,symbol,now):
    root=Path(data)/symbol
    with closing(sqlite3.connect(Path(directory)/"comparison.sqlite",timeout=5)) as db:
        start=initialize(db,now)
        with closing(connect(Path(learning)/"learning.sqlite")) as src:
            lessons=[(t,json.loads(r)) for t,r in src.execute("SELECT enrolled,payload FROM lessons WHERE symbol=? AND enrolled<? ORDER BY enrolled",(symbol,now))]
        with closing(connect(root/"decisions.sqlite")) as src:
            candidates=src.execute("SELECT id,created,context,result FROM decisions WHERE symbol=? AND status='proposed' AND created>=? AND created<=? ORDER BY created,rowid",(symbol,max(start,now-MAX_AGE),now)).fetchall()
        for i,t,c,r in candidates:
            if enroll(db,symbol,(i,t,json.loads(c),json.loads(r or "{}")),lessons,start,now):break
        with closing(connect(root/"market.sqlite")) as src:
            bars={t:json.loads(r) for t,r in src.execute("SELECT stamp,payload FROM samples WHERE symbol=? AND series='candle:5m' AND stamp<?",(symbol,now//STEP*STEP))}
        settle(db,symbol,bars,now)
    return report(directory,symbol)

def main():
    p=argparse.ArgumentParser()
    for a in ("data-dir","directory","learning-dir"):p.add_argument("--"+a,required=True)
    a=p.parse_args();errors=0
    for s in ("BTCUSD","XAUTUSD"):
        try:
            r=run(a.data_dir,a.directory,a.learning_dir,s,int(time.time()));print(encode({"symbol":s,"status":r["status"],"horizons":r["horizons"]}),flush=True)
        except Exception as e:errors+=1;print(encode({"symbol":s,"error":type(e).__name__}),flush=True)
    return int(bool(errors))
if __name__=="__main__":raise SystemExit(main())
