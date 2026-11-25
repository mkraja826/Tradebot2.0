"""Open position trade-price excursion evidence. No execution effects."""
import json,math,sqlite3
from pathlib import Path
from contextlib import closing
from .performance import dec,stamp
from .position_preview import observe
VERSION="open-excursion-v1"

def measure(snapshot,symbol,now,fills,bars,step=60):
    out={"version":VERSION,"status":"position_unverified","execution_effect":"none"}
    v=observe(snapshot,symbol,now)
    if v["position_state"]=="flat":return {**out,"status":"flat"}
    if v["position_state"] not in ("long","short") or snapshot.get("fill_window_complete") is not True:return out
    p=snapshot["positions"][0];pid=p.get("product_id");q=dec(v.get("size"));entry=dec(v.get("entry_price"));mark=dec(v.get("mark_price"))
    created=stamp(p);end=v["observed"]
    if pid is None or q is None or not q or entry is None or entry<=0 or created is None or type(end) is not int:return out
    rows=[];seen=set()
    for f in fills:
        if str(f.get("product_id"))!=str(pid):continue
        t=stamp(f);fid=f.get("id")
        if t is None or fid is None or str(fid) in seen:return out
        seen.add(str(fid));rows.append((t,f))
    rows.sort(key=lambda x:x[0])
    if not rows or rows[-1][0].timestamp()>end:return {**out,"status":"fill_snapshot_timing_unverified"}
    flat=next((i for i in range(len(rows)-1,-1,-1) if dec((rows[i][1].get("new_position") or {}).get("size"))==0),None)
    if flat is None or flat==len(rows)-1:return {**out,"status":"flat_anchor_unavailable"}
    chain=rows[flat+1:];start=chain[0][0];sign=1 if q>0 else -1;prev=0;prices=[]
    if len({t for t,f in rows[flat:]})!=len(rows[flat:]) or abs((created-start).total_seconds())>5:return {**out,"status":"position_lineage_unverified"}
    for i,(t,f) in enumerate(chain):
        size=dec(f.get("size"));price=dec(f.get("price"));after=dec((f.get("new_position") or {}).get("size"))
        side=1 if f.get("side")=="buy" else -1 if f.get("side")=="sell" else 0
        if not side or size is None or size<=0 or price is None or price<=0 or after is None or after!=prev+side*size or after*sign<=0:return out
        if i==0 and (side!=sign or price!=entry):return {**out,"status":"entry_identity_unverified"}
        if i>0 and side==sign:return {**out,"status":"multi_entry_not_supported"}
        prices.append(price);prev=after
    if prev!=q:return {**out,"status":"position_size_unverified"}
    first=math.ceil(start.timestamp()/step)*step;last=end//step*step
    expected=max(0,(last-first)//step);available=0
    extremes=list(prices)
    for t in range(first,last,step):
        r=bars.get(t)
        if not isinstance(r,dict) or r.get("time")!=t:continue
        o,h,l,c=(dec(r.get(k)) for k in ("open","high","low","close"))
        if any(x is None for x in (o,h,l,c)) or not 0<l<=min(o,c)<=max(o,c)<=h:continue
        available+=1;extremes.extend((h,l))
    favorable=max(0,max(extremes)-entry if sign>0 else entry-min(extremes))
    adverse=max(0,entry-min(extremes) if sign>0 else max(extremes)-entry)
    out.update(status="complete_interior_lower_bound" if expected and available==expected else "partial_coverage_lower_bound" if available else "fills_only_lower_bound",
        opened=chain[0][1]["created_at"],observed=end,position_created_at=p["created_at"],entry_price=str(entry),size=str(q),direction=v["position_state"],
        holding_seconds=end-start.timestamp(),frame_seconds=step,expected_interior_bars=expected,observed_interior_bars=available,
        coverage=available/expected if expected else None,mfe_bps=float(favorable/entry*10000),mae_bps=float(adverse/entry*10000),
        current_mark_return_bps=float(sign*(mark-entry)/entry*10000) if mark is not None and mark>0 else None,
        partial_reduction_fills=len(chain)-1,boundary_candles_excluded=True,price_basis="trade_price_extrema_mark_return_separate")
    return out

def report(root,symbol,snapshot,now):
    out={"version":VERSION,"status":"data_unavailable","execution_effect":"none"}
    try:
        root=Path(root)
        with closing(sqlite3.connect((root/"orders.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            fills=[json.loads(r) for r, in db.execute("SELECT detail FROM observed_fills WHERE symbol=?",(symbol,))]
        with closing(sqlite3.connect((root/"market.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            windows={step:{t:json.loads(r) for t,r in db.execute("SELECT stamp,payload FROM samples WHERE symbol=? AND series=?",(symbol,series))} for step,series in ((60,"candle:1m"),(300,"candle:5m"))}
        fine=measure(snapshot,symbol,now,fills,windows[60]);coarse=measure(snapshot,symbol,now,fills,windows[300],300)
        return fine if fine["status"]=="complete_interior_lower_bound" or coarse["status"]!="complete_interior_lower_bound" and fine.get("observed_interior_bars",0)*60>=coarse.get("observed_interior_bars",0)*300 else coarse
    except (sqlite3.Error,ValueError,KeyError,TypeError,AttributeError,ArithmeticError):return out
