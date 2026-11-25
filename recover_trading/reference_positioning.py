"""Independent Bybit ticker snapshot research. No order or AI interfaces."""
import asyncio,argparse,json,sqlite3,time
from contextlib import closing
from pathlib import Path
from .performance import dec
from .liquidation_research import URL,now_ms,report as liquidation_report
TOPIC="tickers.BTCUSDT"
VERSION="reference-positioning-v1"

def normalize(packet,received_ms):
    if not isinstance(packet,dict) or packet.get("topic")!=TOPIC or packet.get("type")!="snapshot":raise ValueError("snapshot_required")
    t=packet.get("ts");d=packet.get("data")
    if type(t) is not int or not 0<=received_ms-t<=30000 or not isinstance(d,dict) or d.get("symbol")!="BTCUSDT":raise ValueError("identity_or_freshness")
    oi,rate,mark,index=(dec(d.get(k)) for k in ("openInterest","fundingRate","markPrice","indexPrice"))
    interval=dec(d.get("fundingIntervalHour"));next_time=dec(d.get("nextFundingTime"))
    if any(v is None for v in (oi,rate,mark,index,interval,next_time)) or min(oi,mark,index,interval)<=0 or interval!=interval.to_integral_value() or next_time!=next_time.to_integral_value() or not t<=next_time<=t+interval*3600000+60000 or abs(rate)>1:raise ValueError("invalid_fields")
    return {"source_ms":t,"received_ms":received_ms,"symbol":"BTCUSDT","open_interest_btc_both_sides":str(oi),"indicative_funding_fraction":str(rate),"indicative_funding_percent":str(rate*100),"indicative_funding_bps":str(rate*10000),"funding_interval_hours":int(interval),"next_funding_ms":int(next_time),"mark_usdt":str(mark),"index_usdt":str(index)}

def save(path,row):
    with closing(sqlite3.connect(path,timeout=5)) as db,db:
        db.execute("CREATE TABLE IF NOT EXISTS positioning (source_ms INTEGER PRIMARY KEY,received_ms INTEGER NOT NULL,payload TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO positioning VALUES (?,?,?)",(row["source_ms"],row["received_ms"],json.dumps(row)))

async def sample(path):
    from websockets.asyncio.client import connect
    async with connect(URL,open_timeout=8,close_timeout=3,ping_interval=None,max_size=2**20,proxy=None) as ws:
        await ws.send(json.dumps({"op":"subscribe","args":[TOPIC]}))
        end=time.monotonic()+10;ack=False;row=None
        while time.monotonic()<end:
            p=json.loads(await asyncio.wait_for(ws.recv(),timeout=max(.1,end-time.monotonic())))
            if p.get("op")=="subscribe":
                if p.get("success") is not True:raise ValueError("subscription_failed")
                ack=True
            elif p.get("topic")==TOPIC and p.get("type")=="snapshot":row=normalize(p,now_ms())
            if ack and row:
                save(path,row);return row
    raise ValueError("snapshot_unavailable")

def report(path,liquidation_path=None,now=None):
    now=now_ms() if now is None else now
    out={"version":VERSION,"source":"bybit_public_linear_BTCUSDT","status":"unavailable","execution_effect":"none","delta_funding_history_units":"unverified"}
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            rows=[json.loads(r) for r, in db.execute("SELECT payload FROM positioning WHERE source_ms<=? ORDER BY source_ms DESC LIMIT 100",(now,))]
        if rows:
            latest=rows[0];fresh=0<=now-latest["source_ms"]<=120000
            out.update(status="fresh_snapshot" if fresh else "stale_snapshot",latest=latest,samples_in_recent_window=len(rows),oi_change_pct={})
            if fresh:
                for minutes in (5,15,60):
                    target=latest["source_ms"]-minutes*60000
                    candidates=[r for r in rows[1:] if 0<=target-r["source_ms"]<=90000]
                    if candidates:
                        prior=max(candidates,key=lambda r:r["source_ms"]);a=dec(latest["open_interest_btc_both_sides"]);b=dec(prior["open_interest_btc_both_sides"])
                        if a is not None and b is not None and min(a,b)>0:out["oi_change_pct"][str(minutes)]={"value":float((a/b-1)*100),"actual_interval_s":(latest["source_ms"]-prior["source_ms"])/1000}
    except (sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError):pass
    if liquidation_path:out["liquidations"]=liquidation_report(liquidation_path,now)
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument("--database",required=True);p.add_argument("--liquidations");p.add_argument("--report",action="store_true");a=p.parse_args()
    if a.report:print(json.dumps(report(a.database,a.liquidations)));return
    try:row=asyncio.run(sample(a.database));print(json.dumps({"status":"sample_saved","source_ms":row["source_ms"]}))
    except Exception as e:print(json.dumps({"status":"sample_failed","error":type(e).__name__}));raise SystemExit(1)
if __name__=="__main__":main()
