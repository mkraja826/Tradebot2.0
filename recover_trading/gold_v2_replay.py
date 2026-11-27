"""Independent forward outcome accounting, not an executable-fill backtest."""
from math import isfinite

def outcome(candidate, bars, *, as_of, horizon=12, cost_bps=15):
    """One candidate, next candle open entry; ambiguous bar is excluded.
    bars are closed 5m Bar objects; as_of is signal time.
    Costs are hypothetical round-trip bps, not actual fees or funding.
    """
    if horizon < 1 or not isfinite(cost_bps) or cost_bps < 0:
        raise ValueError("invalid_assumptions")
    side = {"LONG":1,"SHORT":-1}[candidate["direction"]]
    atr = candidate["atr"]
    stop_mult = candidate["stop_distance_atr_hypothesis"]
    target_mult = candidate["target_distance_atr_hypothesis"]
    if any(not isfinite(x) or x<=0 for x in (atr,stop_mult,target_mult)):
        raise ValueError("invalid_distances")
    boundary=as_of//300*300
    future=[b for b in bars if b.ts>boundary][:horizon]
    if not future:
        return {"status":"pending"}
    if any(b.ts!=boundary+300*(i+1) for i,b in enumerate(future)):
        return {"status":"gap"}
    if any(not all(isfinite(x) for x in (b.o,b.h,b.l,b.c)) or
           not 0<b.l<=min(b.o,b.c)<=max(b.o,b.c)<=b.h for b in future):
        return {"status":"invalid_bar"}
    entry=future[0].o
    stop=entry-side*atr*stop_mult
    target=entry+side*atr*target_mult
    if min(stop,target)<=0:
        return {"status":"invalid_levels"}
    def result(exit_price,reason):
        gross=side*(exit_price/entry-1)*10000
        return {"status":"observed","reason":reason,"gross_bps":gross,
                "net_bps":gross-cost_bps,"cost_bps":cost_bps,
                "entry_reference":entry,"exit_reference":exit_price}
    for i,b in enumerate(future):
        if side*(b.o-stop)<=0:
            return result(b.o,"gap_stop")
        if side*(b.o-target)>=0:
            return result(target,"gap_target_conservative")
        stop_hit=b.l<=stop if side==1 else b.h>=stop
        target_hit=b.h>=target if side==1 else b.l<=target
        if stop_hit and target_hit:
            return {"status":"ambiguous_intrabar"}
        if stop_hit:
            return result(stop,"stop")
        if target_hit:
            return result(target,"target")
    if len(future)<horizon:
        return {"status":"pending"}
    return result(future[-1].c,"horizon")
