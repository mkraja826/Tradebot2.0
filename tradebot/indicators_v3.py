"""Volume and structure features plus validated shared indicator interface."""
from math import isfinite
from statistics import mean,pstdev
from tradebot.market_data_v3 import normalize,MARKETS,FRAMES
from tradebot.indicator_math_v3 import trend,momentum,volatility,ratio

def volume_structure(rows,h,l,c,v):
    tp=[(a+b+d)/3 for a,b,d in zip(h,l,c)]
    out={"obv_window":sum(v[i]*(1 if c[i]>c[i-1] else -1 if c[i]<c[i-1] else 0) for i in range(1,len(c)))}
    out["rvol20"]=ratio(v[-1],mean(v[-21:-1])) if len(v)>20 else None
    out["rolling_vwap20"]=ratio(sum(a*b for a,b in zip(tp[-20:],v[-20:])),sum(v[-20:])) if len(v)>=20 else None
    if len(v)>=20:
        flow=[((2*c[i]-h[i]-l[i])/(h[i]-l[i]) if h[i]>l[i] else 0)*v[i] for i in range(len(v)-20,len(v))]
        out["cmf20"]=ratio(sum(flow),sum(v[-20:]))
    else: out["cmf20"]=None
    if len(v)>=15:
        pos=sum(tp[i]*v[i] for i in range(len(v)-14,len(v)) if tp[i]>tp[i-1])
        neg=sum(tp[i]*v[i] for i in range(len(v)-14,len(v)) if tp[i]<tp[i-1])
        out["mfi14"]=100*pos/(pos+neg) if pos+neg else None
    else: out["mfi14"]=None
    day=rows[-1]["time"]//86400*86400
    indices=[i for i,r in enumerate(rows) if r["time"]>=day]
    complete=rows[indices[0]]["time"]==day
    out["utc_day_vwap"]=ratio(sum(tp[i]*v[i] for i in indices),sum(v[i] for i in indices)) if complete else None
    out["utc_day_high"]=max(h[i] for i in indices) if complete else None
    out["utc_day_low"]=min(l[i] for i in indices) if complete else None
    for n in (10,20,50):
        out[f"prior_high{n}"]=max(h[-n-1:-1]) if len(c)>n else None
        out[f"prior_low{n}"]=min(l[-n-1:-1]) if len(c)>n else None
    o=rows[-1]["open"]; span=h[-1]-l[-1]
    out.update(body_fraction=ratio(abs(c[-1]-o),span),
               upper_wick_fraction=ratio(h[-1]-max(o,c[-1]),span),
               lower_wick_fraction=ratio(min(o,c[-1])-l[-1],span))
    returns=[c[i]/c[i-1]-1 for i in range(1,len(c))]
    out["return_std20_pct"]=100*pstdev(returns[-20:]) if len(returns)>=20 else None
    return out

def features(rows,symbol,frame,*,as_of):
    if symbol not in MARKETS or frame not in FRAMES or not isinstance(rows,list) or not rows:
        raise ValueError("invalid_input")
    bars=normalize(rows,frame,as_of=as_of,count=len(rows))
    h,l,c,v=([r[k] for r in bars] for k in ("high","low","close","volume"))
    result={**trend(h,l,c),**momentum(h,l,c),**volatility(h,l,c),**volume_structure(bars,h,l,c,v)}
    result={k:x if x is not None and isfinite(x) else None for k,x in result.items()}
    return {"symbol":symbol,"frame":frame,"closed_at":bars[-1]["time"]+FRAMES[frame],
            "bars":len(bars),"features":result,"unavailable":sorted(k for k,x in result.items() if x is None)}
