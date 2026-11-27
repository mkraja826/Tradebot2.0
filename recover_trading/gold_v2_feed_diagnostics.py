"""Compare demo and production reference candles; never substitute or repair."""
from statistics import median
from tradebot.market_data_v3 import normalize
from .gold_v2_engine import Bar,quality

def anomalies(bars):
    tr=[max(b.h-b.l,abs(b.h-a.c),abs(b.l-a.c)) for a,b in zip(bars,bars[1:])]
    out=[]
    if len(tr)<41:return out
    for i,t in enumerate(tr):
        base=median(tr[:40] if i<40 else tr[i-40:i])
        if base>0 and t>8*base:
            out.append({"close_timestamp":bars[i+1].ts,"true_range":t,"ratio":t/base})
    return out

def compare(demo,reference):
    """Both input sequences have close timestamps; no assumptions about gaps."""
    refs={b.ts:b for b in reference}
    flags=anomalies(demo)
    ref_flags={x["close_timestamp"] for x in anomalies(reference)}
    result=[]
    for row in flags:
        b=next(b for b in demo if b.ts==row["close_timestamp"])
        r=refs.get(b.ts)
        result.append(dict(row,reference_anomaly=(b.ts in ref_flags) if r else None,
                           close_basis_bps=(b.c/r.c-1)*10000 if r else None,
                           demo_range=b.h-b.l,reference_range=r.h-r.l if r else None))
    return {"demo_anomalies":len(flags),"reference_anomalies":len(ref_flags),
            "matched_anomalies":sum(x["reference_anomaly"] is True for x in result),
            "unmatched_timestamps":sum(x["reference_anomaly"] is None for x in result),
            "details":sorted(result,key=lambda x:x["ratio"],reverse=True)[:10],
            "execution_effect":"none","reference_is_not_demo_fill_price":True}

def probe_frame(client,frame,sec,now,demo,count=250):
    end=now//sec*sec
    try:
        raw=client.candles(symbol="XAUTUSD",resolution=frame,start=end-count*sec,end=end)
        rows=normalize(raw,frame,as_of=now,count=count)
        bars=[Bar(b["time"]+sec,b["open"],b["high"],b["low"],b["close"],b["volume"]) for b in rows]
        return dict(compare(demo,bars),reference_status=quality(bars,sec,now),reference_bars=len(bars))
    except Exception as exc:
        return {"reference_status":"unavailable","reason":type(exc).__name__,
                "demo_anomalies":len(anomalies(demo)),"execution_effect":"none"}
