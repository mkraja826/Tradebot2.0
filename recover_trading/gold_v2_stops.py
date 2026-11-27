"""Closed-bar stop-management research; no broker writes or live orders."""
from math import isfinite

VERSION="gold-v2-stop.1"
POLICIES=("fixed","atr_trail","ema9_trail","structure_trail","hybrid")
STEP=300

def simulate(candidate,bars,*,as_of,horizon=12,cost_bps=15,policy="fixed"):
    if policy not in POLICIES or type(horizon) is not int or horizon<1 or not isfinite(cost_bps) or cost_bps<0:
        raise ValueError("invalid_assumptions")
    side={"LONG":1,"SHORT":-1}[candidate["direction"]]
    initial_atr=candidate["atr"]
    sm=candidate["stop_distance_atr_hypothesis"]
    tm=candidate["target_distance_atr_hypothesis"]
    if any(not isfinite(x) or x<=0 for x in (initial_atr,sm,tm)):
        raise ValueError("invalid_distances")
    boundary=int(as_of)//STEP*STEP
    future=[b for b in bars if b.ts>boundary][:horizon]
    if len(future)!=horizon:return {"status":"pending"}
    if any(b.ts!=boundary+STEP*(i+1) for i,b in enumerate(future)):
        return {"status":"gap"}
    if any(not all(isfinite(x) for x in (b.o,b.h,b.l,b.c)) or
           not 0<b.l<=min(b.o,b.c)<=max(b.o,b.c)<=b.h for b in future):
        return {"status":"invalid_bar"}
    entry=future[0].o
    stop=entry-side*initial_atr*sm
    target=entry+side*initial_atr*tm
    if min(stop,target)<=0:return {"status":"invalid_levels"}
    ema=candidate.get("entry_ema9")
    if not isinstance(ema,(int,float)) or not isfinite(ema) or ema<=0:
        ema=None
    if policy=="ema9_trail" and ema is None:return {"status":"missing_ema_seed"}
    a=initial_atr
    prior_close=entry
    best_close=entry
    changes=[]
    def finish(price,reason,stamp):
        gross=side*(price/entry-1)*10000
        return {"status":"observed","policy":policy,"reason":reason,
                "gross_bps":gross,"net_bps":gross-cost_bps,"cost_bps":cost_bps,
                "entry_reference":entry,"exit_reference":price,"exit_bar_reference":stamp,
                "initial_stop":entry-side*initial_atr*sm,"final_stop":stop,
                "stop_changes":changes}
    for i,b in enumerate(future):
        if side*(b.o-stop)<=0:return finish(b.o,"gap_stop",b.ts-STEP)
        if side*(b.o-target)>=0:return finish(target,"gap_target_conservative",b.ts-STEP)
        sh=b.l<=stop if side==1 else b.h>=stop
        th=b.h>=target if side==1 else b.l<=target
        if sh and th:return {"status":"ambiguous_intrabar"}
        if sh:return finish(stop,"stop",b.ts)
        if th:return finish(target,"target",b.ts)
        if i==horizon-1:return finish(b.c,"horizon",b.ts)
        tr=max(b.h-b.l,abs(b.h-prior_close),abs(b.l-prior_close))
        a+=(tr-a)/14
        prior_close=b.c
        if ema is not None:ema+=0.2*(b.c-ema)
        if side*(b.c-best_close)>0:best_close=b.c
        move=side*(best_close-entry)/initial_atr
        if policy=="fixed" or move<0.75:continue
        levels=[]
        if policy in ("atr_trail","hybrid"):
            levels.append(("atr",best_close-side*1.5*a))
        if policy in ("ema9_trail","hybrid") and ema is not None:
            levels.append(("ema9",ema-side*0.25*a))
        if policy in ("structure_trail","hybrid") and i>=2:
            window=future[i-2:i+1]
            level=min(x.l for x in window) if side==1 else max(x.h for x in window)
            levels.append(("rolling_structure",level-side*0.1*a))
        if policy=="hybrid" and move>=1:
            levels.append(("cost_adjusted_entry",entry*(1+side*cost_bps/10000)))
        # Do not loosen, cross current close, or create a stop beyond target.
        eligible=[(name,p) for name,p in levels if p>0 and side*(p-stop)>0
                  and side*(b.c-p)>0 and side*(target-p)>0]
        if eligible:
            reason,new=max(eligible,key=lambda x:side*x[1])
            changes.append({"observed_close":b.ts,"effective_from":b.ts,
                            "old":stop,"new":new,"reason":reason})
            stop=new
    raise AssertionError("unreachable")

def compare(candidate,bars,*,as_of,horizon=12,cost_bps=15):
    return {"version":VERSION,"execution_effect":"none","results":{
        p:simulate(candidate,bars,as_of=as_of,horizon=horizon,cost_bps=cost_bps,policy=p)
        for p in POLICIES}}
