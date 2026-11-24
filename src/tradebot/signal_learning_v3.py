"""Forward signal observations, not simulated trades or net P&L."""
from collections import defaultdict
from statistics import mean
from tradebot.market_data_v3 import normalize
from tradebot.opportunity_journal_v3 import digest
from tradebot.regime_learning_v3 import classify

HORIZONS=(15,60,240)
def evaluate_event(event,read_bars,*,now):
    if event.get("mode")!="shadow" or event.get("execution_authorized") is not False:
        raise ValueError("shadow_event_required")
    s=event["symbol"]; stamp=event["as_of"]; ctx=event["context"]
    # Context may contain information observed after the candle snapshot.
    observed=ctx["context_observed_at"]
    if type(stamp) is not int or type(observed) is not int or not 0<stamp<=observed<=now:
        raise ValueError("invalid_observation_time")
    if ctx["symbol"]!=s or ctx["as_of"]!=stamp or digest(ctx)!=event["context_sha256"]:
        raise ValueError("invalid_context")
    # Strictly next 5m boundary after the context was available.
    start=(observed//300+1)*300
    out=[]
    for minutes in HORIZONS:
        end=start+minutes*60
        state="pending" if end>now else "missing_candles"
        bars=None
        if end<=now:
            try: bars=normalize(read_bars(s,start,end),"5m",as_of=end,count=minutes//5)
            except ValueError: pass
        for signal in event["new_signals"]:
            if signal["direction"] not in ("LONG","SHORT"): raise ValueError("invalid_direction")
            r={"symbol":s,"event_id":event["event_id"],"rule_id":signal["id"],"frame":signal["frame"],
               "direction":signal["direction"],"closed_at":signal["closed_at"],"horizon_minutes":minutes,
               "regime":classify(ctx,signal),"reference_start":start,"reference_end":end,"status":state,"directional_return_pct":None,
               "favorable_excursion_pct":None,"adverse_excursion_pct":None}
            if bars:
                entry=bars[0]["open"]; close=bars[-1]["close"]; high=max(x["high"] for x in bars); low=min(x["low"] for x in bars)
                sign=1 if signal["direction"]=="LONG" else -1
                r.update(status="observed",directional_return_pct=sign*100*(close/entry-1),
                    favorable_excursion_pct=max(0,100*(high/entry-1) if sign==1 else 100*(1-low/entry)),
                    adverse_excursion_pct=max(0,100*(1-low/entry) if sign==1 else 100*(high/entry-1)))
            out.append(r)
    return out

def aggregate(rows):
    groups=defaultdict(list)
    for r in rows: groups[(r["rule_id"],r["frame"],r["direction"],r["horizon_minutes"])].append(r)
    out=[]
    for (rule,frame,side,h),items in sorted(groups.items()):
        observed=[r for r in items if r["status"]=="observed"]
        values=[r["directional_return_pct"] for r in observed]
        out.append({"rule_id":rule,"frame":frame,"direction":side,"horizon_minutes":h,
            "signals":len(items),"observed":len(values),"pending":sum(r["status"]=="pending" for r in items),
            "missing":sum(r["status"]=="missing_candles" for r in items),
            "positive_direction_fraction":sum(x>0 for x in values)/len(values) if values else None,
            "mean_directional_return_pct":mean(values) if values else None,
            "mean_favorable_excursion_pct":mean(r["favorable_excursion_pct"] for r in observed) if values else None,
            "mean_adverse_excursion_pct":mean(r["adverse_excursion_pct"] for r in observed) if values else None})
    return out
