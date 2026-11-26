"""Read-only LR-V4-B archive adapter; never accesses a broker."""
import argparse
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from .lr_v4b import signals, VERSION


def connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True, timeout=3)


def inspect(market, events, now=None):
    now = int(time.time()) if now is None else int(now)
    result = {"version": VERSION, "symbol": "BTCUSD", "execution_effect": "none",
              "status": "unavailable", "archive_completeness": "unverified"}
    try:
        with closing(connect(events)) as db:
            db.execute("BEGIN")
            session = db.execute("SELECT id,subscribed_ms,heartbeat_ms,ended_ms,status FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
            if not session or session[1] is None or session[2] is None or session[3] is not None or session[4] != "subscribed":
                return {**result, "reason": "no_recorded_subscribed_session"}
            sid, subscribed, heartbeat, _, _ = session
            if not 0 <= now*1000-heartbeat <= 90000:
                return {**result, "reason": "heartbeat_stale_or_future"}
            cutoff = min(now//60*60, heartbeat//60000*60)
            start = max((subscribed+59999)//60000*60, cutoff-86400)
            with closing(connect(market)) as md:
                md.execute("BEGIN")
                candles = [json.loads(x[0]) for x in md.execute(
                    "SELECT payload FROM samples WHERE symbol='BTCUSD' AND series='candle:1m' AND stamp>=? AND stamp<? ORDER BY stamp", (start,cutoff))]
            if not candles:
                return {**result, "reason": "no_candles"}
            cutoff = min(cutoff, candles[-1]["time"]+60)
            # Keep the latest contiguous suffix; do not fill missing candles.
            gap = 0
            for k in range(1,len(candles)):
                if candles[k]["time"] != candles[k-1]["time"]+60:
                    gap = k
            candles = candles[gap:]
            if len(candles)<123 or now-cutoff>120:
                return {**result, "reason": "insufficient_or_stale_candles", "candles":len(candles), "cutoff":cutoff}
            rows = [{"batch_id": a, "ordinal": b, "received_ms": c,
                     "liquidated_position_side": d, "size_btc": e}
                    for a,b,c,d,e in db.execute(
                        "SELECT e.batch_id,e.ordinal,b.received_ms,e.side,e.size FROM events e JOIN batches b ON b.id=e.batch_id WHERE b.session_id=? AND b.received_ms>=? AND b.received_ms<? ORDER BY b.received_ms,e.batch_id,e.ordinal",
                        (sid,candles[0]["time"]*1000,cutoff*1000))]
        found = signals(candles, rows, covered_through=cutoff)
        return {**result, "status":"observed", "cutoff":cutoff, "candles":len(candles),
                "events":len(rows), "session_id":sid,
                "signals_in_window":len(found), "recent_signal":next((s for s in reversed(found) if s["signal_time"]==cutoff),None),
                "latest_signal":found[-1] if found else None,
                "note":"Recorded session heartbeat is not proof of uninterrupted event coverage; shadow only."}
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        return {**result, "reason":type(exc).__name__}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--market",required=True)
    p.add_argument("--events",required=True)
    args=p.parse_args()
    print(json.dumps(inspect(args.market,args.events),allow_nan=False,indent=2))


if __name__=="__main__":
    main()
