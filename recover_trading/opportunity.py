"""Read-only opportunity evidence; no trade selection, sizing or execution policy."""
from math import isfinite
from tradebot.market_data_v3 import FRAMES

LEVELS=("confirmed_swing_high","confirmed_swing_low","prior_high20","prior_low20",
        "donchian20_prior_high","donchian20_prior_low","donchian55_prior_high","donchian55_prior_low")
CONTEXT_LEVELS=("previous_day_high","previous_day_low","previous_day_pivot","previous_day_r1",
                "previous_day_s1","previous_day_r2","previous_day_s2","previous_week_high","previous_week_low")
def positive(x):
    return type(x) in (int,float) and isfinite(x) and x>0

def opportunity(report,direction,*,cost_bps=15.0):
    if type(cost_bps) not in (float,int) or not isfinite(cost_bps) or cost_bps<0:
        raise ValueError("invalid illustrative cost")
    market=report.get("market_context",report.get("market",{}))
    as_of=report["as_of"]; side=direction["direction"]
    ticker=market.get("quotes",{}).get("ticker") or {}
    stamp=ticker.get("timestamp_us"); mark=ticker.get("mark")
    fresh=type(stamp) is int and 0<=as_of*1000000-stamp<=120000000
    price=mark if fresh and positive(mark) else None
    out={"version":"opportunity-evidence-v1","direction":side,"as_of":as_of,
         "source":"demo_mark" if price is not None else None,"reference_price":price,
         "assumed_round_trip_cost_bps":cost_bps,"observed_spread_bps":None,
         "atr_by_frame":{},"nearest_below":None,"nearest_above":None,
         "status":"quote_unavailable" if price is None else "observed",
         "execution_effect":"none"}
    if price is None:return out
    bid,ask=ticker.get("bid"),ticker.get("ask")
    if positive(bid) and positive(ask) and ask>=bid:
        out["observed_spread_bps"]=10000*(ask-bid)/((ask+bid)/2)
    levels=[]
    def add(name,value,source):
        if positive(value) and value!=price:
            levels.append({"name":name,"price":value,"source":source,
                           "distance_bps":round(abs(value/price-1)*10000,3)})
    for frame in ("5m","15m","1h","4h"):
        item=market.get("frames",{}).get(frame,{})
        closed=item.get("closed_at")
        if (item.get("status")!="ready" or type(closed) is not int or
                not 0<=as_of-closed<FRAMES[frame]):
            continue
        f=item.get("features",{}); atr=f.get("atr14")
        if positive(atr):
            bps=atr/price*10000
            out["atr_by_frame"][frame]={"atr":atr,"atr_bps":round(bps,3),
                                         "cost_fraction_of_atr":round(cost_bps/bps,4)}
        for name in LEVELS:add(name,f.get(name),frame)
        for name in CONTEXT_LEVELS:add(name,item.get("gold_context",{}).get(name),frame+":gold_context")
    for name in CONTEXT_LEVELS:add(name,market.get("context",{}).get(name),"market_context")
    below=[x for x in levels if x["price"]<price]
    above=[x for x in levels if x["price"]>price]
    out["nearest_below"]=max(below,key=lambda x:x["price"],default=None)
    out["nearest_above"]=min(above,key=lambda x:x["price"],default=None)
    out["directional_level"]=out["nearest_above"] if side=="LONG" else out["nearest_below"] if side=="SHORT" else None
    out["opposing_level"]=out["nearest_below"] if side=="LONG" else out["nearest_above"] if side=="SHORT" else None
    return out
