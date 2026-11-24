"""Shared pure indicator primitives for completed OHLCV data."""
from math import sqrt
from statistics import mean,pstdev
from tradebot.btc_technical_indicators import _ema_series,_wilder_rsi,_wilder_adx,_macd

def ema(x,n):
    a=_ema_series(x,n)
    return a[-1] if a else None

def wilder(x,n):
    if len(x)<n: return None
    v=mean(x[:n])
    for a in x[n:]: v+=(a-v)/n
    return v

def ratio(a,b):
    return a/b if b else None

def trend(h,l,c):
    out={}
    for n in (9,20,21,50,200):
        out[f"ema{n}"]=ema(c,n)
    for n in (20,50,200):
        out[f"sma{n}"]=mean(c[-n:]) if len(c)>=n else None
    for n in (9,20,50):
        a=_ema_series(c,n)
        out[f"ema{n}_slope"]=a[-1]-a[-2] if len(a)>1 else None
    adx=_wilder_adx(h,l,c) or {}
    out.update({k:adx.get(k) for k in ("adx14","plus_di14","minus_di14")})
    for n,key in ((9,"tenkan9"),(26,"kijun26"),(52,"ichimoku_span_b_unshifted")):
        out[key]=(max(h[-n:])+min(l[-n:]))/2 if len(c)>=n else None
    return out

def momentum(h,l,c):
    out={"rsi14":_wilder_rsi(c)}
    macd=_macd(c) or {}
    out.update({f"macd_{k}":macd.get(k) for k in ("line","signal","histogram")})
    def stoch(end):
        hi=max(h[end-14:end]); lo=min(l[end-14:end])
        return 100*(c[end-1]-lo)/(hi-lo) if hi>lo else None
    ks=[stoch(i) for i in range(len(c)-2,len(c)+1)] if len(c)>=16 else []
    out["stoch_k14"]=stoch(len(c)) if len(c)>=14 else None
    out["stoch_d3"]=mean(ks) if ks and all(x is not None for x in ks) else None
    for n in (5,10,20):
        out[f"roc{n}_pct"]=100*(c[-1]/c[-1-n]-1) if len(c)>n else None
    tp=[(a+b+d)/3 for a,b,d in zip(h,l,c)]
    m=mean(tp[-20:]) if len(tp)>=20 else None
    dev=mean(abs(x-m) for x in tp[-20:]) if m is not None else None
    out["cci20"]=(tp[-1]-m)/(.015*dev) if dev else None
    return out

def volatility(h,l,c):
    tr=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    a=wilder(tr,14)
    out={"atr14":a,"atr14_pct":100*a/c[-1] if a is not None else None}
    m=mean(c[-20:]) if len(c)>=20 else None
    sd=pstdev(c[-20:]) if m is not None else None
    out.update(bb20_mid=m,bb20_upper=m+2*sd if m is not None else None,
               bb20_lower=m-2*sd if m is not None else None,
               bb20_width_pct=400*sd/m if m else None,
               bb20_percent_b=(c[-1]-m+2*sd)/(4*sd) if sd else None)
    k=ema(c,20)
    out.update(keltner20_mid=k,keltner_upper=k+2*a if k is not None and a is not None else None,
               keltner_lower=k-2*a if k is not None and a is not None else None)
    for n in (20,55):
        out[f"donchian{n}_prior_high"]=max(h[-n-1:-1]) if len(c)>n else None
        out[f"donchian{n}_prior_low"]=min(l[-n-1:-1]) if len(c)>n else None
    return out
