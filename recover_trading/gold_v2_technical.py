"""Closed-candle technical evidence for Gold V2; no legacy rules or orders."""
from statistics import median

def wilder(values,n):
    if len(values)<n:
        return []
    out=[sum(values[:n])/n]
    for v in values[n:]:
        out.append(out[-1]+(v-out[-1])/n)
    return out

def momentum(bars,n=14):
    changes=[b.c-a.c for a,b in zip(bars,bars[1:])]
    gains=wilder([max(x,0) for x in changes],n)
    losses=wilder([max(-x,0) for x in changes],n)
    if not gains:
        return None
    g,l=gains[-1],losses[-1]
    return 50.0 if g==l==0 else 100.0 if l==0 else 100-100/(1+g/l)

def directional_strength(bars,n=14):
    tr=[];plus=[];minus=[]
    for a,b in zip(bars,bars[1:]):
        up=b.h-a.h;down=a.l-b.l
        tr.append(max(b.h-b.l,abs(b.h-a.c),abs(b.l-a.c)))
        plus.append(up if up>max(down,0) else 0)
        minus.append(down if down>max(up,0) else 0)
    p=[];m=[];dx=[]
    for t,u,d in zip(wilder(tr,n),wilder(plus,n),wilder(minus,n)):
        p.append(100*u/t if t else 0)
        m.append(100*d/t if t else 0)
        denom=p[-1]+m[-1]
        dx.append(100*abs(p[-1]-m[-1])/denom if denom else 0)
    a=wilder(dx,n)
    return {"adx":a[-1] if a else None,
            "plus_di":p[-1] if p else None,"minus_di":m[-1] if m else None}

def rolling_vwap(bars,n=20):
    if len(bars)<n:
        return None
    window=bars[-n:]
    volume=sum(b.volume for b in window)
    return sum((b.h+b.l+b.c)/3*b.volume for b in window)/volume if volume>0 else None

def swings(bars,k=2,lookback=80):
    """Confirmed strict fractals; last k candles cannot be pivot centers."""
    window=bars[-lookback:]
    highs=[];lows=[]
    for i in range(k,len(window)-k):
        b=window[i]
        others=window[i-k:i]+window[i+1:i+k+1]
        if all(b.h>x.h for x in others): highs.append(b.h)
        if all(b.l<x.l for x in others): lows.append(b.l)
    structure="unknown"
    if len(highs)>=2 and len(lows)>=2:
        if highs[-1]>highs[-2] and lows[-1]>lows[-2]:structure="higher_highs_lows"
        elif highs[-1]<highs[-2] and lows[-1]<lows[-2]:structure="lower_highs_lows"
        else:structure="mixed"
    return {"structure":structure,"last_swing_high":highs[-1] if highs else None,
            "last_swing_low":lows[-1] if lows else None}

def features(bars):
    previous=bars[-21:-1]
    typical_volume=median(b.volume for b in previous) if len(previous)==20 else 0
    return {"rsi14":momentum(bars),**directional_strength(bars),
            "rolling_vwap20":rolling_vwap(bars),
            "relative_volume20":bars[-1].volume/typical_volume if typical_volume>0 else None,
            **swings(bars[:-1])}

def historical_range_flag(bars):
    """Flag anomalous historical true ranges; do not silently repair wicks."""
    tr=[max(b.h-b.l,abs(b.h-a.c),abs(b.l-a.c)) for a,b in zip(bars,bars[1:])]
    # Initial history has no earlier 40-bar baseline; explicitly use its own median.
    if len(tr)<41:
        return False
    initial=median(tr[:40])
    if initial>0 and any(x>8*initial for x in tr[:40]):
        return True
    for i in range(40,len(tr)-1):
        baseline=median(tr[i-40:i])
        if baseline>0 and tr[i]>8*baseline:
            return True
    return False

def candidates(bars,technical,higher,mid,atr_value):
    """Four new families, symmetric long/short; provisional research thresholds."""
    last,prev=bars[-1],bars[-2]
    prior=features(bars[:-1])
    current=technical
    h=max(b.h for b in bars[-21:-1])
    l=min(b.l for b in bars[-21:-1])
    v=current["relative_volume20"];adx=current["adx"];rsi=current["rsi14"]
    vw=current["rolling_vwap20"];pv=prior["rolling_vwap20"]
    found=[]
    for side in (1,-1):
        aligned=higher==mid==side
        di=current["plus_di"] if side==1 else current["minus_di"]
        other=current["minus_di"] if side==1 else current["plus_di"]
        level=h if side==1 else l
        if (aligned and adx is not None and adx>=25 and di is not None and other is not None
            and di>other and v is not None and v>=1.5 and side*(last.c-level)>=0.15*atr_value):
            found.append(("volume_confirmed_breakout",side))
        if (aligned and vw is not None and pv is not None and v is not None and v>=1.0
            and side*(prev.c-pv)<=0 and side*(last.c-vw)>0):
            found.append(("vwap_trend_reclaim",side))
        p_rsi=prior["rsi14"]
        if (adx is not None and adx<20 and rsi is not None and p_rsi is not None
            and vw is not None and side*(last.c-vw)<0
            and ((side==1 and p_rsi<=30<rsi) or (side==-1 and p_rsi>=70>rsi))):
            found.append(("range_rsi_reversal",side))
        swing=current["last_swing_high" if side==1 else "last_swing_low"]
        structure="higher_highs_lows" if side==1 else "lower_highs_lows"
        if (aligned and current["structure"]==structure and swing is not None
            and side*(prev.c-swing)<=0 and side*(last.c-swing)>0.1*atr_value):
            found.append(("structure_continuation",side))
    return found
