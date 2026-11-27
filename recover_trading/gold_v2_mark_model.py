"""Corroborated mark-price volatility research; strict engine remains unchanged."""
from .gold_v2_engine import quality,features,ema,FRAMES
from .gold_v2_mark_aggregation import aggregate
from .gold_v2_feed_diagnostics import anomalies

VERSION="gold-v2-mark-model.1"
def corroborate(primary,other,fine,*,seconds,as_of):
    strict=quality(primary,seconds,as_of)
    out={"strict_quality":strict,"status":strict,"corroborated":[],"unverified":[]}
    if primary and any(x["close_timestamp"]==primary[-1].ts for x in anomalies(primary)):
        return dict(out,status="current_true_range_unverified")
    if strict=="observed":return out
    # Only historical range flags qualify; never bypass invalid data or a current shock.
    if strict!="historical_extreme_range_unverified":return out
    if quality(other,seconds,as_of) not in ("observed","historical_extreme_range_unverified"):
        return out
    derived={b.ts:b for b in aggregate(fine,seconds)}
    peers={b.ts:b for b in other}
    other_flags={x["close_timestamp"] for x in anomalies(other)}
    historical=[x for x in anomalies(primary) if x["close_timestamp"]!=primary[-1].ts]
    for item in historical:
        t=item["close_timestamp"]
        b=next(b for b in primary if b.ts==t)
        a=derived.get(t);p=peers.get(t)
        exact=a is not None and all(getattr(a,k)==getattr(b,k) for k in ("o","h","l","c"))
        # Shared feed evidence is not independent. Require similar range and price
        # as well as matching anomaly timestamps. Tolerances are research hypotheses.
        similar=p is not None and p.h>p.l and .8<=(b.h-b.l)/(p.h-p.l)<=1.25 and abs(b.c/p.c-1)<=.005
        (out["corroborated"] if exact and similar and t in other_flags else out["unverified"]).append(t)
    if historical and not out["unverified"]:
        out["status"]="historical_volatility_corroborated"
    return out

def evaluate_mark(primary,peer,fine,as_of):
    """Separate mark-only candidate families; no volume, no order, no quality override."""
    out={"version":VERSION,"symbol":"XAUTUSD","signal_source":"corroborated_production_mark",
        "execution_eligible":False,"execution_effect":"none","as_of":as_of,"candidates":[]}
    quality_map={}
    for sec in FRAMES:
        b=primary.get(sec,[])
        if sec==900:
            quality_map[str(sec)]=corroborate(b,peer.get(sec,[]),fine,seconds=sec,as_of=as_of)
        else:
            strict=quality(b,sec,as_of)
            current=bool(b and any(x["close_timestamp"]==b[-1].ts for x in anomalies(b)))
            quality_map[str(sec)]={"strict_quality":strict,"status":"current_true_range_unverified" if current else strict}
    out["data_quality"]=quality_map
    if any(x["status"] not in ("observed","historical_volatility_corroborated") for x in quality_map.values()):
        return dict(out,status="data_unusable")
    f={s:features(primary[s]) for s in FRAMES}
    if any(x["atr"]<=0 for x in f.values()):return dict(out,status="zero_atr")
    b=primary[300];last,prior=b[-1],b[-2]
    e9,e21,_,_=f[300]["ema"];a=f[300]["atr"]
    prev9=ema([x.c for x in b[:-1]],9)
    side=f[3600]["direction"]
    signals=[]
    if side and f[900]["direction"]==side and f[900]["separation_atr"]>=.5:
        if side*(prior.c-prev9)<=0 and side*(last.c-e9)>0 and side*(e9-e21)>0:
            signals.append(("mark_trend_pullback",side))
        hi=max(x.h for x in b[-21:-1]);lo=min(x.l for x in b[-21:-1])
        level=hi if side==1 else lo
        if side*(last.c-level)>.15*a and f[300]["adx"] is not None and f[300]["adx"]>=25:
            signals.append(("mark_structure_breakout",side))
    for family,s in signals:
        out["candidates"].append({"family":family,"direction":"LONG" if s==1 else "SHORT",
            "atr":a,"reference_close":last.c,"stop_distance_atr_hypothesis":1.5,
            "target_distance_atr_hypothesis":3.0})
    return dict(out,status="observed",features=f,conflicting_directions=False,
                corroboration="same_exchange_environments_not_independent")
