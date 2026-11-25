"""Experimental reference-venue liquidation hypotheses; never consumed by live direction engine."""
import argparse,json,sqlite3
from pathlib import Path
from contextlib import closing
from decimal import Decimal
from .performance import dec
from .liquidation_research import now_ms
VERSION="liquidation-hypotheses-v1"
WINDOW=300000
THRESHOLDS={"price_move_bps":20,"oi_decline_pct":0.1,"observed_side_size_btc":1,"observed_side_events":2}

def evaluate(latest,prior,events,session,now):
    out={"version":VERSION,"source":"bybit_public_linear_BTCUSDT","execution_effect":"none","thresholds":THRESHOLDS,
         "coverage":"event_completeness_unverified","status":"insufficient_evidence",
         "rules":[{"id":"B17","direction":"LONG","status":"insufficient_evidence"},{"id":"B18","direction":"SHORT","status":"insufficient_evidence"}]}
    if not latest or not prior:return out
    end=latest.get("source_ms");start=prior.get("source_ms")
    if type(end) is not int or type(start) is not int or not 0<=now-end<=120000 or not WINDOW<=end-start<=WINDOW+90000:return out
    if latest.get("symbol")!="BTCUSDT" or prior.get("symbol")!="BTCUSDT":return out
    out["as_of_ms"]=end
    if not session or session.get("status")!="subscribed" or session.get("ended_ms") is not None:return out
    sub=session.get("subscribed_ms");beat=session.get("heartbeat_ms")
    if type(sub) is not int or type(beat) is not int or sub>start or not 0<=now-beat<=45000:return out
    a,b,oi0,oi1,rate=(dec(v) for v in (prior.get("mark_usdt"),latest.get("mark_usdt"),prior.get("open_interest_btc_both_sides"),latest.get("open_interest_btc_both_sides"),latest.get("indicative_funding_fraction")))
    if any(v is None for v in (a,b,oi0,oi1,rate)) or min(a,b,oi0,oi1)<=0:return out
    sizes={"LONG":Decimal(0),"SHORT":Decimal(0)};counts={"LONG":0,"SHORT":0}
    for t,received,side,qty in events:
        if type(t) is not int or type(received) is not int or not start<t<=end or not t<=received<=now or side not in sizes:continue
        n=dec(qty)
        if n is None or n<=0:return out
        sizes[side]+=n;counts[side]+=1
    move=(b/a-1)*10000;oi=(oi1/oi0-1)*100
    out.update(status="observed_research_only" if sum(counts.values()) else "no_observed_events",
        features={"price_move_bps":float(move),"oi_change_pct":float(oi),"funding_fraction":str(rate),
        "interval_s":(end-start)/1000,"observed_sizes_btc":{k:str(v) for k,v in sizes.items()},"observed_counts":counts})
    for r in out["rules"]:
        side="SHORT" if r["id"]=="B17" else "LONG"
        if not counts[side]:
            r["status"]="no_observed_side_events";continue
        flow=sizes[side]>=1 and counts[side]>=2
        falling_oi=oi<=Decimal("-0.1")
        condition=move>=20 and rate<0 if side=="SHORT" else move<=-20
        r["status"]="experimental_signal" if flow and falling_oi and condition else "observed_conditions_not_met"
    return out

def read(root,now=None):
    now=now_ms() if now is None else now;root=Path(root)
    latest=prior=session=None;events=[]
    try:
        with closing(sqlite3.connect((root/"positioning.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            rows=[json.loads(r) for r, in db.execute("SELECT payload FROM positioning WHERE source_ms<=? AND received_ms<=? ORDER BY source_ms DESC LIMIT 12",(now,now))]
        if rows:
            latest=rows[0];end=latest["source_ms"]
            prior=next((r for r in rows[1:] if WINDOW<=end-r["source_ms"]<=WINDOW+90000),None)
        if latest and prior:
            with closing(sqlite3.connect((root/"events.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
                db.execute("BEGIN")
                row=db.execute("SELECT id,subscribed_ms,heartbeat_ms,ended_ms,status FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
                if row:
                    sid,sub,beat,ended,status=row;session=dict(subscribed_ms=sub,heartbeat_ms=beat,ended_ms=ended,status=status)
                    events=db.execute("SELECT e.event_ms,b.received_ms,e.side,e.size FROM events e JOIN batches b ON b.id=e.batch_id WHERE b.session_id=? AND e.event_ms>? AND e.event_ms<=? AND b.received_ms<=?",(sid,prior["source_ms"],end,now)).fetchall()
    except (sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError):return evaluate(None,None,[],None,now)
    return evaluate(latest,prior,events,session,now)

def archive(root,result,now):
    with closing(sqlite3.connect(Path(root)/"hypotheses.sqlite",timeout=5)) as db,db:
        db.execute("CREATE TABLE IF NOT EXISTS observations (bucket INTEGER PRIMARY KEY, observed_ms INTEGER NOT NULL, payload TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?)",(now//60000,now,json.dumps(result,allow_nan=False)))

def main():
    p=argparse.ArgumentParser();p.add_argument("--directory",required=True);p.add_argument("--record",action="store_true");a=p.parse_args();now=now_ms()
    r=read(a.directory,now)
    if a.record:archive(a.directory,r,now)
    print(json.dumps(r,allow_nan=False))
if __name__=="__main__":main()
