"""Explicit, audited family assignments for every recovered candidate."""
from math import isfinite

# One primary family per rule; IDs include deferred research candidates.
GROUPS = {
 "B":{
  "trend":(1,2,4,5,25,26,28,31,38,42,46),
  "momentum":(3,32,40,50),
  "breakout":(6,7,8,9,10,24,29,33,49),
  "reversal":(11,12,13,27,34,36,37,39,43),
  "mean_reversion":(14,16,48),
  "flow":(15,23,30,41),
  "derivatives":(17,18,19,20,21,22,35,45,47),
  "session":(44,),
 },
 "G":{
  "trend":(1,2,3,4,26,29,33,34,38),
  "momentum":(7,28,30,46),
  "breakout":(9,10,16,17,43,48,50),
  "reversal":(8,11,12,13,32,37,39,42),
  "mean_reversion":(14,15,27,35,36),
  "flow":(40,41),
  "macro":(18,19,20,21,22,23,24,45,49),
  "session":(5,6,25,31,44,47),
 }
}
FAMILIES={}
for prefix, groups in GROUPS.items():
    for family, ids in groups.items():
        for i in ids:
            key=f"{prefix}{i:02}"
            if key in FAMILIES:
                raise RuntimeError("duplicate strategy family")
            FAMILIES[key]=family
assert len(FAMILIES)==100

# Relative weights, not probabilities; deliberately conservative experimental priors.
WEIGHTS={
 "trending":{"trend":125,"momentum":115,"breakout":115,"reversal":80,"mean_reversion":75,
             "flow":110,"derivatives":100,"macro":100,"session":100},
 "ranging":{"trend":80,"momentum":90,"breakout":90,"reversal":120,"mean_reversion":125,
            "flow":105,"derivatives":100,"macro":100,"session":100},
 "mixed":{}, "unknown":{},
}
def finite(value):
    return type(value) in (int,float) and isfinite(value)

def market_regime(market):
    frames=market.get("frames",{})
    observations=[]
    for frame in ("1h","4h"):
        item=frames.get(frame,{})
        f=item.get("features",{})
        ema50,ema200,adx=(f.get(k) for k in ("ema50","ema200","adx14"))
        if item.get("status")=="ready" and all(finite(x) for x in (ema50,ema200,adx)):
            observations.append((frame,1 if ema50>ema200 else -1 if ema50<ema200 else 0,adx))
    trending=[side for _,side,adx in observations if adx>=25 and side]
    if not observations:
        regime,bias="unknown","NEUTRAL"
    elif len(trending)==len(observations) and len(set(trending))==1:
        regime,bias="trending","LONG" if trending[0]>0 else "SHORT"
    elif all(adx<20 for _,_,adx in observations):
        regime,bias="ranging","NEUTRAL"
    else:
        regime,bias="mixed","NEUTRAL"
    volatility=[]
    for frame in ("5m","15m"):
        item=frames.get(frame,{})
        value=item.get("features",{}).get("atr14_percentile100")
        if item.get("status")=="ready" and finite(value) and 0<=value<=100:
            volatility.append(value)
    return {"regime":regime,"trend_bias":bias,"volatility":"high" if any(x>=80 for x in volatility)
            else "normal" if volatility else "unknown","trend_frames":len(observations)}

def family_weight(family,regime):
    weight=WEIGHTS[regime["regime"]].get(family,100)
    if regime["volatility"]=="high" and family in ("breakout","flow","momentum"):
        weight+=10
    return weight

def weighted_votes(groups,regime):
    """Cap each family/direction; diminishing marginal credit for related rules."""
    from collections import Counter
    totals={"LONG":0,"SHORT":0}; details={}
    for side in totals:
        counts=Counter(FAMILIES[v["id"]] for v in groups[side])
        for family,n in sorted(counts.items()):
            weight=family_weight(family,regime)
            # Hundredths of weight; first 100%, next 25%, third 25%, then cap.
            score=weight*(100+25*min(n-1,2))
            totals[side]+=score
            details.setdefault(family,{})[side]={"count":n,"weight":weight,"score":score/100}
    return totals,details
