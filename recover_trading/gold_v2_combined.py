"""Integrated position-management hypotheses, not a broker execution engine.

All quantities are normalized to one initial synthetic position. Closed-bar
decisions apply only to subsequent bars; simultaneous intrabar events are
excluded when their ordering changes the result.
"""
from math import isfinite

VERSION="gold-v2-combined.1"
POLICIES=("fixed","hybrid_exit","hybrid_scaling")
STEP=300

def simulate(candidate,bars,*,as_of,horizon=12,cost_bps=15,policy="fixed"):
    if (policy not in POLICIES or type(horizon) is not int or horizon<1
            or not isfinite(cost_bps) or not 0<=cost_bps<10000):
        raise ValueError("invalid_assumptions")
    side={"LONG":1,"SHORT":-1}[candidate["direction"]]
    a0=candidate["atr"];sm=candidate["stop_distance_atr_hypothesis"];tm=candidate["target_distance_atr_hypothesis"]
    if any(not isfinite(x) or x<=0 for x in (a0,sm,tm)):
        raise ValueError("invalid_distances")
    boundary=int(as_of)//STEP*STEP
    future=[b for b in bars if b.ts>boundary][:horizon]
    if len(future)!=horizon:return {"status":"pending"}
    if any(b.ts!=boundary+STEP*(i+1) for i,b in enumerate(future)):
        return {"status":"gap"}
    if any(not all(isfinite(x) for x in (b.o,b.h,b.l,b.c)) or
           not 0<b.l<=min(b.o,b.c)<=max(b.o,b.c)<=b.h for b in future):
        return {"status":"invalid_bar"}
    entry=future[0].o;stop=entry-side*a0*sm
    target=entry+side*a0*tm;partial_price=entry+side*a0*tm/2
    if min(stop,target,partial_price)<=0:return {"status":"invalid_levels"}
    active=policy!="fixed";scaling=policy=="hybrid_scaling"
    fee=cost_bps/20000
    lots=[(1.0,entry)]
    realized=0.0;fees=fee
    initial_risk=(abs(entry-stop)+fee*(entry+stop))/entry
    peak_qty=1.0;adds=0;reduced=False;partial=False;extended=False
    events=[{"action":"entry","units":1.0,"price":entry,"bar_reference":boundary}]
    changes=[];pending=None;rejected_adds=0
    ema=candidate.get("entry_ema9")
    if type(ema) not in (float,int) or not isfinite(ema) or ema<=0:ema=None
    atr=a0;prior=entry;best=entry
    def qty():return sum(q for q,_ in lots)
    def net_at(price,extra=None):
        book=lots if extra is None else lots+[extra]
        extra_fee=0 if extra is None else fee*extra[0]*extra[1]/entry
        return realized-fees-extra_fee+sum(q*(side*(price-p)-fee*price)/entry for q,p in book)
    def close(amount,price,action,stamp):
        nonlocal realized,fees
        left=amount
        while left>1e-10 and lots:
            q,p=lots[0];take=min(q,left)
            realized+=side*take*(price-p)/entry
            fees+=fee*take*price/entry
            left-=take
            if q-take<=1e-10:lots.pop(0)
            else:lots[0]=(q-take,p)
        if left>1e-8:raise AssertionError("overclose")
        events.append({"action":action,"units":amount-left,"price":price,"bar_reference":stamp})
    def finish(price,reason,stamp):
        close(qty(),price,"exit",stamp)
        return {"status":"observed","policy":policy,"reason":reason,
                "gross_bps_initial_notional":realized*10000,
                "net_bps_initial_notional":(realized-fees)*10000,
                "cost_bps_initial_notional":fees*10000,"peak_quantity_units":peak_qty,
                "initial_stop_risk_bps":initial_risk*10000,"adds":adds,"reduced":reduced,
                "partial":partial,"rejected_adds":rejected_adds,"events":events,"bracket_changes":changes}
    for i,b in enumerate(future):
        stamp=b.ts-STEP
        # Gap stop first; at favorable gaps, honor existing partial and final limits.
        if side*(b.o-stop)<=0:return finish(b.o,"gap_stop",stamp)
        if active and not partial and side*(b.o-partial_price)>=0:
            close(qty()/2,partial_price,"partial",stamp);partial=True
        if side*(b.o-target)>=0:return finish(target,"gap_target_conservative",stamp)
        if pending=="exit":return finish(b.o,"giveback_next_open",stamp)
        if pending=="reduce" and not reduced and not partial and side*(b.o-entry)<0:
            close(qty()/2,b.o,"reduce",stamp);reduced=True
        if pending=="add" and not partial and not reduced and adds<5:
            # Do not add unless the existing stop would keep modeled total
            # loss within the initial stop-risk budget, including turnover costs.
            if (side*(b.o-entry)>0 and qty()+1<=6
                    and net_at(stop,(1.0,b.o))>=-initial_risk-1e-12):
                lots.append((1.0,b.o));fees+=fee*b.o/entry;adds+=1
                events.append({"action":"add","units":1.0,"price":b.o,"bar_reference":stamp})
            else:rejected_adds+=1
        pending=None
        peak_qty=max(peak_qty,qty())
        sh=b.l<=stop if side==1 else b.h>=stop
        th=b.h>=target if side==1 else b.l<=target
        ph=active and not partial and (b.h>=partial_price if side==1 else b.l<=partial_price)
        if sh and (th or ph):return {"status":"ambiguous_intrabar"}
        if sh:return finish(stop,"stop",b.ts)
        if ph:
            close(qty()/2,partial_price,"partial",b.ts);partial=True
        if th:return finish(target,"target",b.ts)
        if i==horizon-1:return finish(b.c,"horizon",b.ts)
        if not active:continue
        tr=max(b.h-b.l,abs(b.h-prior),abs(b.l-prior))
        atr+=(tr-atr)/14;prior=b.c
        if ema is not None:ema+=0.2*(b.c-ema)
        if side*(b.c-best)>0:best=b.c
        move=side*(b.c-entry)/a0;best_move=side*(best-entry)/a0
        if not extended and i>=1:
            p=future[i-1]
            if (move>=0.6*tm and side*(b.c-p.c)>0 and side*(p.c-p.o)>0
                    and side*(b.c-b.o)>=0.25*a0):
                new=target+side*a0
                if new>0:
                    changes.append({"kind":"target","old":target,"new":new,"effective_from":b.ts})
                    target=new;extended=True
        if best_move>=0.75:
            levels=[best-side*1.5*atr]
            if ema is not None:levels.append(ema-side*0.25*atr)
            if i>=2:
                window=future[i-2:i+1]
                levels.append((min(x.l for x in window) if side==1 else max(x.h for x in window))-side*0.1*atr)
            if best_move>=1:
                # Net episode breakeven accounts for realized P&L and remaining lots.
                weighted=sum(q*p for q,p in lots)
                denom=qty()*(side-fee)
                breakeven=(side*weighted+(fees-realized)*entry)/denom
                levels.append(breakeven)
            eligible=[p for p in levels if p>0 and side*(p-stop)>0
                      and side*(b.c-p)>0 and side*(target-p)>0]
            if eligible:
                new=max(eligible,key=lambda p:side*p)
                changes.append({"kind":"stop","old":stop,"new":new,"effective_from":b.ts})
                stop=new
        # Exit > reduction > addition. Never add after a reduction or partial.
        if best_move>=1 and best_move-move>=0.75:pending="exit"
        elif scaling and not partial and not reduced and move<=-0.5:pending="reduce"
        elif scaling and not partial and not reduced and adds<5 and move>=0.5*(adds+1):pending="add"
    raise AssertionError("unreachable")

def compare(candidate,bars,*,as_of,horizon=12,cost_bps=15):
    return {"version":VERSION,"execution_effect":"none","results":{
        p:simulate(candidate,bars,as_of=as_of,horizon=horizon,cost_bps=cost_bps,policy=p)
        for p in POLICIES}}
