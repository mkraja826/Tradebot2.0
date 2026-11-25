"""Read-only price excursions within reconciled, single-entry episodes."""
import json,math,sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from .performance import dec,stamp
VERSION="trade-excursion-v1"

def measure(episode,fills,bars,step):
    """Use only full candles strictly inside the actual holding interval."""
    start=stamp({"created_at":episode.get("opened")});end=stamp({"created_at":episode.get("closed")})
    out={"opened":episode.get("opened"),"closed":episode.get("closed"),"direction":episode.get("direction"),"decision_id":episode.get("decision_id"),"status":"unverified"}
    if start is None or end is None or end<=start:return out
    rows=[(t,f) for f in fills if (t:=stamp(f)) is not None and start<=t<=end]
    rows.sort(key=lambda x:x[0])
    if len(rows)!=episode.get("fills") or len(rows)<2 or rows[0][0]!=start or rows[-1][0]!=end or len({t for t,f in rows})!=len(rows):return out
    sign=1 if episode.get("direction")=="LONG" else -1 if episode.get("direction")=="SHORT" else 0
    entry=dec(rows[0][1].get("price"));prev=0;prices=[]
    for i,(t,f) in enumerate(rows):
        size=dec(f.get("size"));price=dec(f.get("price"));after=dec((f.get("new_position") or {}).get("size"))
        side=1 if f.get("side")=="buy" else -1 if f.get("side")=="sell" else 0
        if not sign or not side or size is None or size<=0 or price is None or price<=0 or after is None or after!=prev+side*size:return out
        if i==0 and side!=sign:return out
        if i>0 and (side==sign or abs(after)>=abs(prev) or after*sign<0):out["status"]="multi_entry_or_reversal_not_supported";return out
        prev=after;prices.append(price)
    if prev!=0:return out
    a,b=start.timestamp(),end.timestamp()
    first=math.ceil(a/step)*step;last=math.floor(b/step)*step
    expected=max(0,(last-first)//step);available=0;extremes=list(prices)
    for t in range(first,last,step):
        r=bars.get(t)
        if not isinstance(r,dict) or r.get("time")!=t:continue
        o,h,l,c=(dec(r.get(k)) for k in ("open","high","low","close"))
        if any(v is None for v in (o,h,l,c)) or not 0<l<=min(o,c)<=max(o,c)<=h:continue
        available+=1;extremes.extend([h,l])
    favorable=max(0,sign*(max(extremes) - entry) if sign>0 else entry-min(extremes))
    adverse=max(0,entry-min(extremes) if sign>0 else max(extremes)-entry)
    out.update(status="complete_interior_lower_bound" if expected and available==expected else "partial_coverage_lower_bound" if available else "fills_only_lower_bound",
        frame_seconds=step,expected_interior_bars=expected,observed_interior_bars=available,
        coverage=available/expected if expected else None,entry_price=str(entry),
        mfe_bps=float(favorable/entry*10000),mae_bps=float(adverse/entry*10000),
        gross_exit_price_excursion_bps=float(sign*(prices[-1]-entry)/entry*10000),
        holding_seconds=b-a,boundary_candles_excluded=True)
    return out

def report(root,symbol,performance):
    root=Path(root);out={"version":VERSION,"symbol":symbol,"execution_effect":"none","status":"unavailable","episodes":[]}
    try:
        with closing(sqlite3.connect((root/"orders.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            fills=[json.loads(r) for r, in db.execute("SELECT detail FROM observed_fills WHERE symbol=?",(symbol,))]
        with closing(sqlite3.connect((root/"market.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            windows={step:{t:json.loads(r) for t,r in db.execute("SELECT stamp,payload FROM samples WHERE symbol=? AND series=?",(symbol,series))} for step,series in ((60,"candle:1m"),(300,"candle:5m"))}
        rows=[]
        for ep in performance.get("recent_episodes",[]):
            fine=measure(ep,fills,windows[60],60)
            coarse=measure(ep,fills,windows[300],300)
            # Choose full interior coverage where available, then finer resolution.
            chosen=fine if fine["status"]=="complete_interior_lower_bound" or coarse["status"]!="complete_interior_lower_bound" and fine.get("observed_interior_bars",0)*60>=coarse.get("observed_interior_bars",0)*300 else coarse
            rows.append(chosen)
        out.update(status="observed",episodes=rows,counts=dict(Counter(r["status"] for r in rows)),
            limitations=["Trade-price OHLC, not mark-price or liquidation path. Excludes partial boundary candles; extremes are observed lower bounds, not exact excursions.",
            "Only reconciled closed episodes with one opening fill and subsequent reductions; no multi-entry, reversal or open-position inference.",
            "Demo feed anomalies may affect extrema. No interpolation, public-reference substitution, fee or leverage adjustment.",
            "Exit excursion refers to final fill, not weighted realized return for partial exits."])
    except (sqlite3.Error,ValueError,KeyError,TypeError,AttributeError,ArithmeticError):pass
    return out
