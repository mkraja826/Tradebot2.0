"""Audit native mark OHLC against exact same-source 5m aggregation.

No interpolation, volume reconstruction, execution or replacement of native data.
"""
from math import isfinite
from tradebot.market_data_v3 import normalize
from .gold_v2_engine import Bar,quality
from .gold_v2_feed_diagnostics import anomalies

def aggregate(bars,seconds):
    if seconds not in (900,3600):raise ValueError("unsupported_frame")
    if not bars:return []
    for i,b in enumerate(bars):
        if type(b.ts) is not int or b.ts%300 or (i and b.ts-bars[i-1].ts!=300):
            raise ValueError("incomplete_five_minute_series")
        if not all(isfinite(x) for x in (b.o,b.h,b.l,b.c)) or not 0<b.l<=min(b.o,b.c)<=max(b.o,b.c)<=b.h:
            raise ValueError("invalid_ohlc")
    n=seconds//300
    groups={}
    for b in bars:
        end=((b.ts-1)//seconds+1)*seconds
        groups.setdefault(end,[]).append(b)
    out=[]
    for end,items in sorted(groups.items()):
        if len(items)!=n:continue
        if [b.ts for b in items]!=list(range(end-seconds+300,end+1,300)):
            raise ValueError("invalid_group")
        out.append(Bar(end,items[0].o,max(b.h for b in items),min(b.l for b in items),items[-1].c,0))
    return out

def audit(native,derived,*,seconds,as_of):
    indexed={b.ts:b for b in derived}
    flags={x["close_timestamp"] for x in anomalies(native)}
    matched=[];missing=0;differences=[]
    for b in native:
        d=indexed.get(b.ts)
        if d is None:missing+=1;continue
        delta=max(abs(getattr(b,k)-getattr(d,k)) for k in ("o","h","l","c"))
        row={"close_timestamp":b.ts,"max_ohlc_difference":delta,
             "native_range":b.h-b.l,"aggregated_range":d.h-d.l}
        differences.append(delta)
        if b.ts in flags:matched.append(row)
    return {"native_quality":quality(native,seconds,as_of),
            "aggregated_quality":quality(derived,seconds,as_of),
            "native_anomalies":len(flags),"aggregated_anomalies":len(anomalies(derived)),
            "matched_bars":len(differences),"unmatched_native_bars":missing,
            "max_ohlc_difference":max(differences,default=None),
            "anomaly_comparisons":matched[:20],"execution_effect":"none"}

def collect(reader,name,seconds,end,count):
    raw=reader(dict(symbol="MARK:XAUTUSD",resolution=name,start=end-count*seconds,end=end))
    rows=normalize([dict(r,volume=0) for r in raw],name,as_of=end,count=count)
    return [Bar(r["time"]+seconds,r["open"],r["high"],r["low"],r["close"],0) for r in rows]

def probe(reader,now):
    # Exactly 250 complete 15m bars require 750 consecutive 5m bars.
    # Align the endpoints before collecting, rather than comparing partial bars.
    end=now//900*900
    try:
        native=collect(reader,"15m",900,end,250)
        fine=collect(reader,"5m",300,end,750)
        return audit(native,aggregate(fine,900),seconds=900,as_of=now)
    except Exception as exc:
        return {"status":"unavailable","reason":type(exc).__name__,"execution_effect":"none"}
