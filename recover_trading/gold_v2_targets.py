"""Gold V2 take-profit hypotheses, fixed quantity and fixed initial stop.
All discretionary changes are based on closed bars. No broker effects.
"""
from math import isfinite

VERSION="gold-v2-target.1"
POLICIES=("fixed","partial","trend_extension","profit_giveback","partial_and_giveback")
STEP=300

def simulate(candidate,bars,*,as_of,horizon=12,cost_bps=15,policy="fixed"):
    if policy not in POLICIES or type(horizon) is not int or horizon<1 or not isfinite(cost_bps) or cost_bps<0:
        raise ValueError("invalid_assumptions")
    side={"LONG":1,"SHORT":-1}[candidate["direction"]]
    a=candidate["atr"]; sm=candidate["stop_distance_atr_hypothesis"]; tm=candidate["target_distance_atr_hypothesis"]
    if any(not isfinite(x) or x<=0 for x in (a,sm,tm)):
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
    stop=entry-side*a*sm
    target=entry+side*a*tm
    partial_price=entry+side*a*tm/2
    if min(stop,target,partial_price)<=0:return {"status":"invalid_levels"}
    qty=1.0; gross=0.0; events=[]; changes=[]
    partial=policy in ("partial","partial_and_giveback")
    best=0.0; pending=False; extended=False
    def exit_fill(q,price,reason,stamp):
        nonlocal qty,gross
        qty-=q
        gross+=q*side*(price/entry-1)*10000
        events.append({"quantity_fraction":q,"price":price,"reason":reason,"bar_reference":stamp})
    def finish(price,reason,stamp):
        exit_fill(qty,price,reason,stamp)
        return {"status":"observed","policy":policy,"reason":reason,"gross_bps":gross,
                "net_bps":gross-cost_bps,"cost_bps":cost_bps,"entry_reference":entry,
                "target_changes":changes,"exit_fills":events,
                "timing":"bar_reference_not_exact_fill_time"}
    for i,b in enumerate(future):
        stamp=b.ts-STEP
        # Existing stop/target orders precede discretionary next-open exits.
        if side*(b.o-stop)<=0:return finish(b.o,"gap_stop",stamp)
        if side*(b.o-target)>=0:
            if partial and qty==1:
                exit_fill(0.5,partial_price,"partial_gap_conservative",stamp)
            return finish(target,"gap_target_conservative",stamp)
        if partial and qty==1 and side*(b.o-partial_price)>=0:
            exit_fill(0.5,partial_price,"partial_gap_conservative",stamp)
        if pending:return finish(b.o,"giveback_next_open",stamp)
        sh=b.l<=stop if side==1 else b.h>=stop
        th=b.h>=target if side==1 else b.l<=target
        ph=partial and qty==1 and (b.h>=partial_price if side==1 else b.l<=partial_price)
        if sh and (th or ph):return {"status":"ambiguous_intrabar"}
        if sh:return finish(stop,"stop",b.ts)
        if ph:exit_fill(0.5,partial_price,"partial_target",b.ts)
        if th:return finish(target,"target",b.ts)
        if i==horizon-1:return finish(b.c,"horizon",b.ts)
        move=side*(b.c-entry)/a
        best=max(best,move)
        if policy=="trend_extension" and not extended and i>=1:
            prev=future[i-1]
            # Extend once before target hit, on two favorable closes and strong body.
            if (move>=0.6*tm and side*(b.c-prev.c)>0 and side*(prev.c-prev.o)>0
                    and side*(b.c-b.o)>=0.25*a):
                new=target+side*a
                if new>0:
                    changes.append({"old":target,"new":new,"effective_from":b.ts})
                    target=new;extended=True
        if policy in ("profit_giveback","partial_and_giveback") and best>=1 and best-move>=0.75:
            pending=True
    raise AssertionError("unreachable")

def compare(candidate,bars,*,as_of,horizon=12,cost_bps=15):
    return {"version":VERSION,"execution_effect":"none","results":{
        p:simulate(candidate,bars,as_of=as_of,horizon=horizon,cost_bps=cost_bps,policy=p)
        for p in POLICIES}}
