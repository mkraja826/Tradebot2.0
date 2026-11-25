"""Display-only technical studies on completed, contiguous demo OHLCV."""
from collections import deque
from math import sqrt
from statistics import mean

class Average:
    def __init__(self,n,alpha):
        self.n=n;self.alpha=alpha;self.seed=[];self.value=None
    def add(self,x):
        if self.value is None:
            self.seed.append(x)
            if len(self.seed)==self.n:self.value=mean(self.seed)
        else:self.value+=self.alpha*(x-self.value)
        return self.value

def studies(rows,step):
    result=[];prev=None;day=None;vwap_ok=False
    def reset():
        return ({n:Average(n,2/(n+1)) for n in (9,12,20,26,50,200)},Average(9,2/10),Average(14,1/14),Average(14,1/14),Average(14,1/14),deque(maxlen=20),deque(maxlen=20))
    emas,signal,up,down,atr,closes,ranges=reset()
    pv=vol=0
    for c in rows:
        t=c["time"];close=c["close"];h=c["high"];l=c["low"];v=c["volume"]
        gap=prev is None or t-prev["time"]!=step
        if gap:emas,signal,up,down,atr,closes,ranges=reset()
        if t//86400!=day:
            day=t//86400;pv=vol=0;vwap_ok=t%86400==0 and step<86400
        elif gap:vwap_ok=False
        pv+=(h+l+close)/3*v;vol+=v
        r={"time":t,"vwap":pv/vol if vwap_ok and vol>0 else None}
        values={n:a.add(close) for n,a in emas.items()}
        for n in (9,20,50,200):r["ema"+str(n)]=values[n]
        macd=values[12]-values[26] if values[12] is not None and values[26] is not None else None
        sig=signal.add(macd) if macd is not None else None
        r.update(macd=macd,macd_signal=sig,macd_hist=macd-sig if sig is not None else None)
        r["support"]=min(x[0] for x in ranges) if len(ranges)==20 else None
        r["resistance"]=max(x[1] for x in ranges) if len(ranges)==20 else None
        ranges.append((l,h));closes.append(close)
        mid=mean(closes) if len(closes)==20 else None
        sd=sqrt(mean((x-mid)**2 for x in closes)) if mid is not None else None
        r.update(bb_mid=mid,bb_upper=mid+2*sd if mid is not None else None,bb_lower=mid-2*sd if mid is not None else None)
        rsi=None
        if not gap:
            delta=close-prev["close"];g=up.add(max(delta,0));loss=down.add(max(-delta,0))
            if g is not None and loss is not None:rsi=50 if g==loss==0 else 100 if loss==0 else 100-100/(1+g/loss)
        r["rsi"]=rsi
        r["atr"]=atr.add(h-l if gap else max(h-l,abs(h-prev["close"]),abs(l-prev["close"])))
        result.append(r);prev=c
    return result
