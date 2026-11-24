"""Restore specifically quarantined XAUTUSD 5m candles only with reproducible
Delta India public 5m and 1m consensus. Preserve originals and evidence in
SQLite; never alter broker orders, protections, model rules, or other symbols.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.parse
import urllib.request
from tradebot.market_integrity import suspect_candle_times

HOSTS = ("https://api.india.delta.exchange", "https://cdn.india.deltaex.org")
STAMPS = (1795446300,)
POLICY = "XAUTUSD-public-delta-dual-host-1m-rebuild-v1"
KEYS = ("open", "high", "low", "close", "volume")


def canonical(row, step):
    if type(row) is not dict or type(row.get("time")) is not int:
        raise ValueError("Invalid public candle")
    t = row["time"]
    if t % step:
        raise ValueError("Misaligned candle")
    try:
        vals = tuple(Decimal(str(row[k])) for k in KEYS)
    except (ValueError, KeyError, TypeError):
        raise ValueError("Invalid OHLCV") from None
    if any(not x.is_finite() for x in vals):
        raise ValueError("Non-finite OHLCV")
    o,h,l,c,v = vals
    if not 0 < l <= min(o,c) <= max(o,c) <= h or v < 0:
        raise ValueError("Impossible OHLCV")
    return (t,*vals)


def serialized(c):
    return dict(time=c[0], **{name:str(c[i]) for i,name in enumerate(KEYS,1)})


def get_candles(host, resolution, first, last, *, opener=None):
    if host not in HOSTS or resolution not in ("5m", "1m"):
        raise ValueError("Untrusted public host or resolution")
    query = urllib.parse.urlencode(dict(
        symbol="XAUTUSD", resolution=resolution,
        start=first-60, end=last+360))
    url = host + "/v2/history/candles?" + query
    request = urllib.request.Request(url, headers={
        "Accept":"application/json", "User-Agent":"TB2-ReadOnly-CandleEvidence"})
    with (opener or urllib.request.urlopen)(request, timeout=7) as response:
        result = json.load(response)
    rows = result.get("result") if type(result) is dict else None
    if type(rows) is not list or not 0 < len(rows) <= 100:
        raise ValueError("Incomplete or malformed public response")
    out = {}
    for row in rows:
        c = canonical(row, 300 if resolution=="5m" else 60)
        if first <= c[0] < last+300:
            if c[0] in out:
                raise ValueError("Conflicting or repeated candle")
            out[c[0]] = c
    return out


def five_from_one(data,t):
    bars = [data.get(t+60*i) for i in range(5)]
    if any(x is None for x in bars):
        raise ValueError("Missing one-minute component")
    return (t,bars[0][1],max(b[2] for b in bars),
            min(b[3] for b in bars),bars[-1][4],
            sum((b[5] for b in bars),Decimal(0)))


def corroborate(stamps, *, opener=None):
    stamps=tuple(sorted(stamps))
    if (not stamps or len(stamps)>12 or len(set(stamps))!=len(stamps)
            or any(type(x) is not int or x<=0 or x%300 for x in stamps)):
        raise ValueError("Invalid XAUTUSD quarantine targets")
    evidence={}
    for host in HOSTS:
        evidence[host] = {
            res:get_candles(host,res,stamps[0],stamps[-1],opener=opener)
            for res in ("5m","1m")}
    candidates={}
    hashes={}
    for t in stamps:
        expected=evidence[HOSTS[0]]["5m"].get(t)
        if expected is None:
            raise ValueError("Missing primary Delta five-minute candle")
        for host in HOSTS:
            d=evidence[host]
            if d["5m"].get(t)!=expected or five_from_one(d["1m"],t)!=expected:
                raise ValueError("Public Delta five-minute and one-minute evidence disagree")
            material=[serialized(expected)]+[
                serialized(d["1m"][t+60*i]) for i in range(5)]
            hashes[host+"@"+str(t)] = hashlib.sha256(
                json.dumps(material,sort_keys=True).encode()).hexdigest()
        candidates[t]=expected
    return candidates,hashes


def database(path):
    path=Path(path)
    if path.name!="delta-demo-candles.sqlite" or path.is_symlink() or not path.is_file():
        raise ValueError("Unexpected Gold archive")
    return sqlite3.connect(path,timeout=8)


def originals(db,stamps,proposed):
    if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):
        raise ValueError("Unhealthy candle archive")
    before={}
    for t in stamps:
        row=db.execute("SELECT t,o,h,l,c,v,reason FROM candle_quarantine "
                       "WHERE symbol='XAUTUSD' AND t=?",(t,)).fetchone()
        if row is None or row[-1]!="conflicting_historical_refetch":
            raise ValueError("Original Delta conflict evidence unavailable")
        if db.execute("SELECT count(*) FROM candles WHERE symbol='XAUTUSD' "
                      "AND t=?",(t,)).fetchone()[0]:
            raise ValueError("Active candle already present")
        before[t]=row
        near=db.execute("SELECT symbol,t,o,h,l,c,v FROM candles "
                        "WHERE symbol='XAUTUSD' AND t BETWEEN ? AND ?",
                        (t-900,t+900)).fetchall()
        replacement=("XAUTUSD",t,*(float(v) for v in proposed[t][1:]))
        if t in suspect_candle_times(near+[replacement]):
            raise ValueError("Recovered candle fails neighbor checks")
    return before


def recover(path, stamps=STAMPS, *, apply=False, opener=None):
    stamps=tuple(sorted(stamps))
    proposed, hashes=corroborate(stamps,opener=opener)
    with closing(database(path)) as db:
        old=originals(db,stamps,proposed)
    result=dict(policy=POLICY,stamps=list(stamps),
                candidates={str(t):serialized(proposed[t]) for t in stamps},
                cross_resolution_verified=True,
                original_conflicts_preserved=len(old),applied=False)
    if not apply:
        return result
    with closing(database(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        if originals(db,stamps,proposed)!=old:
            raise ValueError("Quarantine changed during corroboration")
        db.execute("""CREATE TABLE IF NOT EXISTS candle_recovery_audit(
            symbol TEXT NOT NULL,t INTEGER NOT NULL,policy TEXT NOT NULL,
            original_json TEXT NOT NULL,replacement_json TEXT NOT NULL,
            source_sha256_json TEXT NOT NULL,observed_utc TEXT NOT NULL,
            PRIMARY KEY(symbol,t))""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS candle_recovery_audit_no_update
            BEFORE UPDATE ON candle_recovery_audit BEGIN
            SELECT RAISE(ABORT, 'immutable recovery evidence'); END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS candle_recovery_audit_no_delete
            BEFORE DELETE ON candle_recovery_audit BEGIN
            SELECT RAISE(ABORT, 'immutable recovery evidence'); END""")
        now=datetime.now(timezone.utc).isoformat()
        for t in stamps:
            row=old[t]
            orig=dict(time=row[0],open=row[1],high=row[2],
                      low=row[3],close=row[4],volume=row[5],reason=row[6])
            db.execute("INSERT INTO candle_recovery_audit VALUES(?,?,?,?,?,?,?)",
                ("XAUTUSD",t,POLICY,json.dumps(orig,sort_keys=True),
                 json.dumps(serialized(proposed[t]),sort_keys=True),
                 json.dumps({k:v for k,v in hashes.items()
                             if k.endswith("@"+str(t))},sort_keys=True),now))
            db.execute("DELETE FROM candle_quarantine WHERE symbol='XAUTUSD' "
                       "AND t=? AND reason='conflicting_historical_refetch'",(t,))
            if db.execute("SELECT changes()").fetchone()[0]!=1:
                raise ValueError("Original quarantined evidence changed")
            db.execute("INSERT INTO candles VALUES(?,?,?,?,?,?,?)",
                       ("XAUTUSD",t,*(float(v) for v in proposed[t][1:])))
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):
            raise ValueError("Post-recovery archive integrity failed")
        db.commit()
    result["applied"]=True
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",default="data")
    parser.add_argument("--apply",action="store_true")
    a=parser.parse_args()
    root=Path(a.data_dir)
    if not root.is_dir() or root.is_symlink():
        raise SystemExit("Untrusted archive root")
    print(json.dumps(recover(root/"delta-demo-candles.sqlite",apply=a.apply),
                     sort_keys=True))
    from tradebot.gold_recent24h import inspect_recent_gold_window
    r=inspect_recent_gold_window(root)
    print("WINDOW",json.dumps({k:r.get(k) for k in (
        "status","reason","retained_bars","quarantined_bars",
        "complete_contiguous_24h","trade_authorized")},sort_keys=True))

if __name__=="__main__":
    main()

