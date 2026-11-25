"""Public Bybit BTCUSDT liquidation research; no credentials or trading interfaces."""
import argparse,asyncio,hashlib,json,sqlite3,time,signal
from pathlib import Path
from decimal import Decimal
from contextlib import closing
from .performance import dec
URL="wss://stream.bybit.com/v5/public/linear"
TOPIC="allLiquidation.BTCUSDT"
VERSION="liquidation-research-v1"

def normalize(packet,received_ms):
    if not isinstance(packet,dict) or packet.get("topic")!=TOPIC or packet.get("type")!="snapshot":raise ValueError("topic")
    ts=packet.get("ts");data=packet.get("data")
    if type(ts) is not int or not 0<=received_ms-ts<=120000 or not isinstance(data,list) or len(data)>10000:raise ValueError("envelope")
    rows=[]
    for r in data:
        if not isinstance(r,dict) or r.get("s")!="BTCUSDT" or r.get("S") not in ("Buy","Sell"):raise ValueError("identity")
        t=r.get("T");qty=dec(r.get("v"));price=dec(r.get("p"))
        if type(t) is not int or not 0<=ts-t<=120000 or qty is None or qty<=0 or price is None or price<=0:raise ValueError("event")
        rows.append({"event_ms":t,"position_side":"LONG" if r["S"]=="Buy" else "SHORT","executed_size":str(qty.normalize()),"bankruptcy_price":str(price.normalize())})
    # No exchange event IDs: only identical batch fingerprints, not proven event identities.
    raw=json.dumps([ts,rows],sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode()).hexdigest(),ts,rows

class Journal:
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=5)
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, started_ms INTEGER NOT NULL, subscribed_ms INTEGER, heartbeat_ms INTEGER, ended_ms INTEGER, status TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, session_id INTEGER NOT NULL, source_ms INTEGER NOT NULL, received_ms INTEGER NOT NULL, event_count INTEGER NOT NULL, duplicate_count INTEGER NOT NULL DEFAULT 0)")
            self.db.execute("CREATE TABLE IF NOT EXISTS events (batch_id TEXT, ordinal INTEGER, event_ms INTEGER NOT NULL, side TEXT NOT NULL, size TEXT NOT NULL, bankruptcy_price TEXT NOT NULL, PRIMARY KEY(batch_id,ordinal))")
    def start(self,now):
        with self.db:
            self.db.execute("UPDATE sessions SET status='interrupted' WHERE ended_ms IS NULL")
            return self.db.execute("INSERT INTO sessions(started_ms,status) VALUES (?,'connecting')",(now,)).lastrowid
    def subscribed(self,ident,now):
        with self.db:self.db.execute("UPDATE sessions SET subscribed_ms=?,heartbeat_ms=?,status='subscribed' WHERE id=?",(now,now,ident))
    def heartbeat(self,ident,now):
        with self.db:self.db.execute("UPDATE sessions SET heartbeat_ms=? WHERE id=? AND status='subscribed'",(now,ident))
    def end(self,ident,now,status):
        with self.db:self.db.execute("UPDATE sessions SET ended_ms=?,status=? WHERE id=?",(now,status,ident))
    def record(self,ident,packet,now):
        batch,ts,rows=normalize(packet,now)
        with self.db:
            r=self.db.execute("INSERT OR IGNORE INTO batches(id,session_id,source_ms,received_ms,event_count) VALUES (?,?,?,?,?)",(batch,ident,ts,now,len(rows)))
            if not r.rowcount:
                self.db.execute("UPDATE batches SET duplicate_count=duplicate_count+1 WHERE id=?",(batch,))
                return False
            self.db.executemany("INSERT INTO events VALUES (?,?,?,?,?,?)",[(batch,i,x["event_ms"],x["position_side"],x["executed_size"],x["bankruptcy_price"]) for i,x in enumerate(rows)])
        return True

def now_ms():return time.time_ns()//1000000

async def collect(path):
    from websockets.asyncio.client import connect
    j=Journal(path);delay=5
    try:
        while True:
            sid=j.start(now_ms());status="disconnected"
            try:
                async with connect(URL,open_timeout=10,close_timeout=5,ping_interval=None,max_size=2**20,proxy=None) as ws:
                    await ws.send(json.dumps({"op":"subscribe","args":[TOPIC]}))
                    ack=json.loads(await asyncio.wait_for(ws.recv(),timeout=10))
                    if ack.get("op")!="subscribe" or ack.get("success") is not True:raise ValueError("subscription")
                    j.subscribed(sid,now_ms());delay=5
                    last_ping=time.monotonic();last_pong=last_ping
                    while True:
                        tick=time.monotonic()
                        if tick-last_pong>45:raise TimeoutError("heartbeat")
                        if tick-last_ping>=20:
                            await ws.send('{"op":"ping"}');last_ping=tick
                        try:packet=json.loads(await asyncio.wait_for(ws.recv(),timeout=2))
                        except asyncio.TimeoutError:continue
                        if packet.get("op")=="pong" or (packet.get("op")=="ping" and packet.get("success") is True and packet.get("ret_msg")=="pong"):
                            last_pong=time.monotonic();j.heartbeat(sid,now_ms())
                        else:j.record(sid,packet,now_ms())
            except asyncio.CancelledError:
                status="stopped";raise
            except Exception as exc:
                status=type(exc).__name__;print(json.dumps({"status":status,"source":"bybit_public_linear"}),flush=True)
            finally:j.end(sid,now_ms(),status)
            await asyncio.sleep(delay);delay=min(delay*2,120)
    finally:j.db.close()

def report(path,now=None):
    now=now_ms() if now is None else now
    out={"version":VERSION,"source":"bybit_public_linear_BTCUSDT","status":"unavailable","execution_effect":"none","coverage":"unverified_no_sequence_or_event_id"}
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            s=db.execute("SELECT started_ms,subscribed_ms,heartbeat_ms,ended_ms,status FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
            if not s:return out
            out.update(status="heartbeat_observed" if s[4]=="subscribed" and s[3] is None and s[2] is not None and 0<=now-s[2]<=45000 else "not_connected_or_unverified",
                session_status=s[4],session_started_ms=s[0],last_heartbeat_ms=s[2],session_count=db.execute("SELECT count(*) FROM sessions").fetchone()[0],
                batches=db.execute("SELECT count(*) FROM batches").fetchone()[0],duplicate_batches=db.execute("SELECT coalesce(sum(duplicate_count),0) FROM batches").fetchone()[0])
            # Empty observations are not asserted to be zero market liquidations.
            out["observed_events"]=[{"side":side,"event_count":n} for side,n in db.execute("SELECT side,count(*) FROM events WHERE event_ms>=? AND event_ms<=? GROUP BY side",(now-900000,now))]
            out["window_seconds"]=900
    except (sqlite3.Error,ValueError,TypeError):pass
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument("--database",required=True);p.add_argument("--report",action="store_true");a=p.parse_args()
    if a.report:print(json.dumps(report(a.database)));return
    async def run():
        task=asyncio.create_task(collect(a.database));loop=asyncio.get_running_loop()
        for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,task.cancel)
        try:await task
        except asyncio.CancelledError:pass
    asyncio.run(run())
if __name__=="__main__":main()
