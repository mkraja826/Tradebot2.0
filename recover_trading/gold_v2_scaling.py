"""Paired fixed-size and scaling hypotheses for Gold V2; no exchange operations.

Units are fractions of one initial synthetic notional, not account allocation.
Orders are simulated only at a subsequent bar open, after a closed-bar signal.
"""
from math import isfinite

VERSION="gold-v2-sizing.1"
POLICIES=("fixed","add_winners","reduce_losers","add_and_reduce")
MAX_UNITS=6
STEP=300

def simulate(candidate,bars,*,as_of,horizon=12,cost_bps=15,policy="fixed"):
    if policy not in POLICIES or type(horizon) is not int or horizon<1 or not isfinite(cost_bps) or cost_bps<0:
        raise ValueError("invalid_assumptions")
    side={"LONG":1,"SHORT":-1}[candidate["direction"]]
    atr=candidate["atr"]
    sm=candidate["stop_distance_atr_hypothesis"]
    tm=candidate["target_distance_atr_hypothesis"]
    if any(not isfinite(x) or x<=0 for x in (atr,sm,tm)):
        raise ValueError("invalid_distances")
    boundary=int(as_of)//STEP*STEP
    future=[b for b in bars if b.ts>boundary][:horizon]
    if len(future)!=horizon:
        return {"status":"pending"}
    if any(b.ts!=boundary+STEP*(i+1) for i,b in enumerate(future)):
        return {"status":"gap"}
    if any(not all(isfinite(x) for x in (b.o,b.h,b.l,b.c)) or
           not 0<b.l<=min(b.o,b.c)<=max(b.o,b.c)<=b.h for b in future):
        return {"status":"invalid_bar"}
    entry=future[0].o
    stop=entry-side*atr*sm
    target=entry+side*atr*tm
    if min(stop,target)<=0:
        return {"status":"invalid_levels"}
    # Quantity is normalized so the first fill costs one initial notional.
    lots=[(1.0,entry)]
    fees=cost_bps/20000
    cost=fees
    gross=0.0
    peak=1.0
    peak_notional=1.0
    adds=0
    reduced=False
    pending=None
    events=[{"action":"entry","price":entry,"units":1.0,"bar_open":boundary}]
    def qty():
        return sum(q for q,_ in lots)
    def remove(amount,price,action,stamp):
        nonlocal gross,cost
        left=amount
        while left>1e-10 and lots:
            q,p=lots[0]
            take=min(q,left)
            gross+=side*take*(price-p)/entry
            cost+=fees*take*price/entry
            left-=take
            if q-take<=1e-10:lots.pop(0)
            else:lots[0]=(q-take,p)
        events.append({"action":action,"price":price,"units":amount-left,"bar_open":stamp})
    def finish(price,reason,stamp):
        remove(qty(),price,"exit",stamp)
        return {"status":"observed","reason":reason,"policy":policy,
                "gross_bps_initial_notional":gross*10000,
                "net_bps_initial_notional":(gross-cost)*10000,
                "cost_bps_initial_notional":cost*10000,
                "peak_quantity_units":peak,"peak_marked_notional_multiple":peak_notional,
                "adds":adds,"reduced":reduced,"events":events}
    for i,b in enumerate(future):
        stamp=b.ts-STEP
        # Existing bracket has precedence over a pending resize at the open.
        if side*(b.o-stop)<=0:
            return finish(b.o,"gap_stop",stamp)
        if side*(b.o-target)>=0:
            return finish(target,"gap_target_conservative",stamp)
        if pending=="add":
            # Require a favorable open and no more than five additions.
            if side*(b.o-entry)>0 and adds<5 and qty()+1<=MAX_UNITS:
                lots.append((1.0,b.o))
                cost+=fees*b.o/entry
                adds+=1
                events.append({"action":"add","price":b.o,"units":1.0,"bar_open":stamp})
        elif pending=="reduce" and not reduced and side*(b.o-entry)<0:
            remove(qty()/2,b.o,"reduce",stamp)
            reduced=True
        pending=None
        peak=max(peak,qty())
        peak_notional=max(peak_notional,qty()*b.h/entry)
        sh=b.l<=stop if side==1 else b.h>=stop
        th=b.h>=target if side==1 else b.l<=target
        if sh and th:
            return {"status":"ambiguous_intrabar"}
        if sh:return finish(stop,"stop",b.ts)
        if th:return finish(target,"target",b.ts)
        if i==horizon-1:return finish(b.c,"horizon",b.ts)
        move=side*(b.c-entry)/atr
        # Prior close only; never fill at the close that generated the action.
        if policy in ("reduce_losers","add_and_reduce") and not reduced and move<=-0.5:
            pending="reduce"
        elif policy in ("add_winners","add_and_reduce") and adds<5 and not reduced and move>=0.5*(adds+1):
            pending="add"

def compare(candidate,bars,*,as_of,horizon=12,cost_bps=15):
    return {"version":VERSION,"cost_bps_per_round_trip":cost_bps,
            "execution_effect":"none","results":{
        p:simulate(candidate,bars,as_of=as_of,horizon=horizon,cost_bps=cost_bps,policy=p)
        for p in POLICIES}}
