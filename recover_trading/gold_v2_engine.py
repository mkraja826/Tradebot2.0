"""Clean-slate XAUTUSD research engine. No exchange or AI dependencies.

All input candles must be CLOSED, UTC epoch close timestamps, oldest first.
Output is a research hypothesis, never an order. No legacy strategy imports.
"""
from dataclasses import dataclass
from math import isfinite
from statistics import median

VERSION = "gold-v2-alpha.2"
FRAMES = (300, 900, 3600)

@dataclass(frozen=True)
class Bar:
    ts: int
    o: float
    h: float
    l: float
    c: float
    volume: float = 0.0

def quality(bars, seconds, as_of):
    if len(bars) < 201:
        return "insufficient_history"
    for i, b in enumerate(bars):
        if not all(isfinite(v) for v in (b.o,b.h,b.l,b.c,b.volume)):
            return "nonfinite"
        if not (0 < b.l <= min(b.o,b.c) <= max(b.o,b.c) <= b.h and b.volume >= 0):
            return "invalid_ohlcv"
        if b.ts > as_of or b.ts % seconds or (i and b.ts-bars[i-1].ts != seconds):
            return "future_misaligned_or_gap"
    if as_of-bars[-1].ts >= seconds:
        return "stale"
    ranges = [b.h-b.l for b in bars[-41:-1]]
    baseline = median(ranges)
    if baseline <= 0:
        return "flat_or_invalid_baseline"
    if bars[-1].h-bars[-1].l > 8*baseline:
        return "extreme_range_unverified"
    return "observed"

def ema(values, n):
    out = sum(values[:n])/n
    alpha = 2/(n+1)
    for x in values[n:]:
        out += alpha*(x-out)
    return out

def atr(bars, n=14):
    tr = [max(b.h-b.l, abs(b.h-a.c), abs(b.l-a.c))
          for a,b in zip(bars,bars[1:])]
    value = sum(tr[:n])/n
    for x in tr[n:]:
        value += (x-value)/n
    return value

def features(bars):
    closes = [b.c for b in bars]
    e = [ema(closes, n) for n in (9,21,50,200)]
    a = atr(bars)
    direction = 1 if e[0]>e[1]>e[2]>e[3] else -1 if e[0]<e[1]<e[2]<e[3] else 0
    return {"ema":e, "atr":a, "direction":direction,
            "separation_atr":abs(e[1]-e[2])/a if a>0 else 0.0}

def evaluate(frames, as_of):
    """Evaluate one point in time with no broker side effects."""
    flags = {str(s):quality(frames.get(s,()),s,as_of) for s in FRAMES}
    out = {"version":VERSION,"symbol":"XAUTUSD","as_of":as_of,
           "execution_effect":"none","data_quality":flags,"candidates":[],
           "external_context":"not_integrated"}
    if any(v!="observed" for v in flags.values()):
        return dict(out, status="data_unusable")
    f = {s:features(frames[s]) for s in FRAMES}
    if any(f[s]["atr"]<=0 for s in FRAMES):
        return dict(out,status="zero_atr")
    b = frames[300]
    last, prior = b[-1], b[-2]
    a = f[300]["atr"]
    higher = f[3600]["direction"]
    mid = f[900]["direction"]
    regime = "trend" if higher and higher==mid and f[900]["separation_atr"]>=0.5 else "mixed_or_range"
    high = max(x.h for x in b[-22:-2])
    low = min(x.l for x in b[-22:-2])
    e9,e21,_,_ = f[300]["ema"]
    prior_e9 = ema([x.c for x in b[:-1]],9)
    signals = []
    if regime=="trend" and higher==1 and prior.c<=prior_e9 and last.c>e9 and e9>e21:
        signals.append(("trend_pullback",1))
    if regime=="trend" and higher==-1 and prior.c>=prior_e9 and last.c<e9 and e9<e21:
        signals.append(("trend_pullback",-1))
    if prior.c>high and high-0.25*a<=last.l<=high+0.25*a and last.c>high:
        signals.append(("breakout_retest",1))
    if prior.c<low and low-0.25*a<=last.h<=low+0.25*a and last.c<low:
        signals.append(("breakout_retest",-1))
    if last.l<low and last.c>low and last.c>last.o:
        signals.append(("liquidity_sweep",1))
    if last.h>high and last.c<high and last.c<last.o:
        signals.append(("liquidity_sweep",-1))
    for family, side in signals:
        out["candidates"].append({"family":family,"direction":"LONG" if side==1 else "SHORT",
                                 "higher_timeframe_alignment":"aligned" if higher==side else "opposed" if higher==-side else "neutral",
                                 "reference_close":last.c,"atr":a,
                                 "stop_distance_atr_hypothesis":1.5,
                                 "target_distance_atr_hypothesis":3.0})
    return dict(out,status="observed",regime=regime,features=f,
                conflicting_directions=len({s for _,s in signals})>1)
