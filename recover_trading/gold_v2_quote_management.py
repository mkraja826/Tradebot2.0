"""Paired quote-sampled management hypotheses; not fills or order instructions."""
from decimal import Decimal as D
from .gold_v2_entry_adapter import positive

VERSION="gold-v2-quote-management.1"
POLICIES=("fixed","adaptive_exit","adaptive_scaling")
COSTS=(5,15,30)

def simulate(plan,samples,*,policy,cost_bps):
    if policy not in POLICIES or cost_bps not in COSTS:raise ValueError("unknown_policy")
    side=D({"LONG":1,"SHORT":-1}[plan["direction"]])
    entry=positive(plan["demo_book_entry_reference"]);a=positive(plan["translated_atr"])
    stop=positive(plan["hypothetical_stop"]);target=positive(plan["hypothetical_target"])
    if not side*(entry-stop)>0 or not side*(target-entry)>0:raise ValueError("invalid_bracket")
    if not samples:raise ValueError("empty_samples")
    fee=D(cost_bps)/20000
    lots=[(D(1),entry)];gross=D(0);fees=fee*entry
    budget=abs(entry-stop)+fee*(entry+stop)
    peak=D(1);best=entry;adds=0;reduced=False;partial=False;extended=False
    pending=None;events=[];last_stamp=-1
    active=policy!="fixed";scaling=policy=="adaptive_scaling"
    partial_level=(entry+target)/2
    def qty():return sum(q for q,p in lots)
    def net_at(px,extra=None):
        book=lots+([extra] if extra else [])
        return gross-fees-(fee*extra[0]*extra[1] if extra else 0)+sum(q*(side*(px-p)-fee*px) for q,p in book)
    def close(n,px,action,stamp):
        nonlocal gross,fees
        left=n
        while left>0:
            q,p=lots.pop(0);take=min(q,left);left-=take
            gross+=take*side*(px-p);fees+=fee*take*px
            if q>take:lots.insert(0,(q-take,p))
        events.append({"action":action,"stamp":stamp,"units":str(n),"price":str(px)})
    def finish(px,why,stamp):
        close(qty(),px,"exit",stamp)
        return {"policy":policy,"reason":why,"net_bps_initial_notional":float((gross-fees)/entry*10000),
                "fees_bps_initial_notional":float(fees/entry*10000),"peak_units":float(peak),
                "adds":adds,"partial":partial,"reduced":reduced,"events":events,"fill_verified":False}
    for i,(stamp,q) in enumerate(samples):
        if type(stamp) is not int or stamp<=last_stamp:raise ValueError("nonchronological_samples")
        last_stamp=stamp
        mark=positive(q["mark_price"]);bid=positive(q["best_bid"]);ask=positive(q["best_ask"])
        if bid>ask:raise ValueError("crossed_book")
        exit_px=bid if side==1 else ask
        add_px=ask if side==1 else bid
        # Existing mark-triggered bracket precedes any pending management.
        if side*(mark-stop)<=0:return finish(exit_px,"sampled_stop",stamp)
        if side*(mark-target)>=0:return finish(exit_px,"sampled_target",stamp)
        if pending=="giveback":return finish(exit_px,"sampled_giveback",stamp)
        if pending=="partial" and not partial and side*(mark-partial_level)>=0:
            close(qty()/2,exit_px,"partial",stamp);partial=True
        elif pending=="reduce" and not reduced and not partial and side*(mark-entry)<0:
            close(qty()/2,exit_px,"reduce",stamp);reduced=True
        elif pending=="add" and not reduced and not partial and adds<5:
            # Experimental modeled stop-loss budget, not proof of actual loss limit.
            if side*(add_px-entry)>0 and net_at(stop,(D(1),add_px))>=-budget:
                lots.append((D(1),add_px));fees+=fee*add_px;adds+=1
                peak=max(peak,qty())
                events.append({"action":"add","stamp":stamp,"units":"1","price":str(add_px)})
        pending=None
        if i==len(samples)-1:return finish(exit_px,"horizon_sample",stamp)
        if not active:continue
        if side*(mark-best)>0:best=mark
        move=side*(mark-entry)/a;best_move=side*(best-entry)/a
        if not extended and move>=D("1.8") and side*(target+a*side-mark)>0:
            target+=side*a;extended=True
            events.append({"action":"target_extension","stamp":stamp,"level":str(target)})
        if best_move>=D(".75"):
            levels=[best-side*D("1.5")*a]
            if best_move>=1:
                weighted=sum(q*p for q,p in lots)
                levels.append((side*weighted+fees-gross)/(qty()*(side-fee)))
            eligible=[p for p in levels if p>0 and side*(p-stop)>0 and side*(mark-p)>0 and side*(target-p)>0]
            if eligible:
                stop=max(eligible,key=lambda p:side*p)
                events.append({"action":"stop_tighten","stamp":stamp,"level":str(stop)})
        if best_move>=1 and best_move-move>=D(".75"):pending="giveback"
        elif not partial and side*(mark-partial_level)>=0:pending="partial"
        elif scaling and not reduced and not partial and move<=-D(".5"):pending="reduce"
        elif scaling and not reduced and not partial and adds<5 and move>=D(".5")*(adds+1):pending="add"
    raise AssertionError("unreachable")

def compare(plan,samples):
    return {"version":VERSION,"execution_effect":"none","results":{
        str(c):{p:simulate(plan,samples,policy=p,cost_bps=c) for p in POLICIES} for c in COSTS}}
