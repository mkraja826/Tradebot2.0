"""Specialized point-in-time technical features for both assets."""
from statistics import mean
from tradebot.indicator_math_v3 import ema,ratio
from tradebot.btc_technical_indicators import _wilder_rsi,_macd

def atr_series(h,l,c,n):
    tr=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    if len(tr)<n: return []
    out=[mean(tr[:n])]
    for x in tr[n:]: out.append(out[-1]+(x-out[-1])/n)
    return out

def supertrend(h,l,c,n=10,m=3):
    atr=atr_series(h,l,c,n)
    if not atr: return None,None
    upper=lower=prev=None
    side=-1
    for i,a in enumerate(atr,n):
        mid=(h[i]+l[i])/2; u=mid+m*a; d=mid-m*a
        upper=u if upper is None or u<upper or c[i-1]>upper else upper
        lower=d if lower is None or d>lower or c[i-1]<lower else lower
        if prev is not None:
            side=1 if side==-1 and c[i]>upper else -1 if side==1 and c[i]<lower else side
        prev=lower if side==1 else upper
    return prev,side

def pivots(x,width=2,high=True):
    cmp=(lambda a,b:a>b) if high else (lambda a,b:a<b)
    return [i for i in range(width,len(x)-width)
            if all(cmp(x[i],x[j]) for j in range(i-width,i+width+1) if j!=i)]

def divergence(c,price,points,high,oscillator):
    if len(points)<2: return None
    a,b=points[-2:]
    x=oscillator(c[:a+1]); y=oscillator(c[:b+1])
    if x is None or y is None: return None
    return int(price[b]>price[a] and y<x if high else price[b]<price[a] and y>x)

def advanced_technicals(bars):
    h,l,c=([r[k] for r in bars] for k in ("high","low","close"))
    out={}
    out["supertrend10_3"],out["supertrend_direction"]=supertrend(h,l,c)
    atr=atr_series(h,l,c,14)
    out["atr14_percentile100"]=100*sum(x<=atr[-1] for x in atr[-101:-1])/100 if len(atr)>=101 else None
    highs=pivots(h); lows=pivots(l,high=False)
    out["confirmed_swing_high"]=h[highs[-1]] if highs else None
    out["confirmed_swing_low"]=l[lows[-1]] if lows else None
    out["swing_high_time"]=bars[highs[-1]]["time"] if highs else None
    out["swing_low_time"]=bars[lows[-1]]["time"] if lows else None
    for name,osc in (("rsi",_wilder_rsi),("macd",lambda x:(_macd(x) or {}).get("line"))):
        out[name+"_bearish_divergence"]=divergence(c,h,highs,True,osc)
        out[name+"_bullish_divergence"]=divergence(c,l,lows,False,osc)
    direction=None; start=end=None
    if highs and lows:
        if highs[-1]>lows[-1] and h[highs[-1]]>l[lows[-1]]:
            direction=1; start=l[lows[-1]]; end=h[highs[-1]]
        elif lows[-1]>highs[-1] and l[lows[-1]]<h[highs[-1]]:
            direction=-1; start=h[highs[-1]]; end=l[lows[-1]]
    out["fib_direction"]=direction
    for label,f in (("382",.382),("500",.5),("618",.618),("786",.786)):
        out["fib_"+label]=end+(start-end)*f if direction else None
    out["inside_bar"]=int(h[-1]<h[-2] and l[-1]>l[-2]) if len(c)>1 else None
    return out

def daily_pivots(previous):
    h,l,c=(previous[k] for k in ("high","low","close"))
    p=(h+l+c)/3
    return {"pivot":p,"r1":2*p-l,"s1":2*p-h,"r2":p+h-l,"s2":p-h+l}
