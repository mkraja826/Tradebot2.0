"""Deterministic demo direction consensus over the recovered strategy registry."""
from collections import defaultdict
from .regime import market_regime, weighted_votes, FAMILIES
from tradebot.bitcoin_strategies_v3 import RULES as BTC_RULES, DEFERRED as BTC_DEFERRED
from tradebot.gold_strategies_v3 import RULES as GOLD_RULES, DEFERRED as GOLD_DEFERRED

REGISTRY = {"BTCUSD": (BTC_RULES, BTC_DEFERRED), "XAUTUSD": (GOLD_RULES, GOLD_DEFERRED)}

def direction_for(report):
    rules, deferred = REGISTRY[report["symbol"]]
    registered = {r.id:r for r in rules}
    votes = defaultdict(set)
    frames = defaultdict(set)
    for signal in report.get("signals", []):
        ident, frame, side = signal["id"], signal["frame"], signal["direction"]
        if (ident not in registered or frame not in registered[ident].frames
                or side not in ("LONG","SHORT") or type(signal.get("closed_at")) is not int
                or not 0 < signal["closed_at"] <= report["as_of"]):
            raise ValueError("Invalid direction signal")
        votes[ident].add(side)
        frames[ident].add(frame)
    groups = {k:[] for k in ("LONG","SHORT","CONFLICT")}
    for ident,sides in sorted(votes.items()):
        side = next(iter(sides)) if len(sides)==1 else "CONFLICT"
        groups[side].append({"id":ident,"name":registered[ident].name,"frames":sorted(frames[ident])})
    longs, shorts = len(groups["LONG"]), len(groups["SHORT"])
    regime=market_regime(report.get("market_context",report.get("market",{})))
    totals,families=weighted_votes(groups,regime)
    side = "LONG" if totals["LONG"]>totals["SHORT"] else "SHORT" if totals["SHORT"]>totals["LONG"] else "NEUTRAL"
    raw=totals["LONG"]+totals["SHORT"]
    return {"version":"regime-weighted-v2","direction":side,"long_votes":longs,"short_votes":shorts,
            "regime":regime,"family_scores":families,"long_score":totals["LONG"]/100,"short_score":totals["SHORT"]/100,
            "long_share":round(totals["LONG"]/raw,4) if raw else None,
            "conflicting_rules":len(groups["CONFLICT"]),"votes":groups,
            "implemented_rules":len(rules),"deferred_rules":len(deferred),
            "reason":"regime_weighted_family_consensus" if side!="NEUTRAL" else
                     "balanced_or_conflicting" if votes else "no_active_signal"}

def compact_context(context):
    """Keep direction and current evidence; archive full evidence in journal."""
    market=context.get("market",{})
    names=("ema9","ema20","ema21","ema50","ema200","rsi14","adx14","atr14","atr14_pct",
           "macd_histogram","supertrend_direction","supertrend10_3","rvol20","cmf20",
           "rolling_vwap20","utc_day_vwap","donchian20_prior_high","donchian20_prior_low",
           "confirmed_swing_high","confirmed_swing_low","bb20_upper","bb20_lower",
           "prior_high20","prior_low20","plus_di14","minus_di14","stoch_k14")
    frames={}
    for frame,item in market.get("frames",{}).items():
        features=item.get("features",{})
        frames[frame]={"status":item.get("status"),"closed_at":item.get("closed_at"),
                       "candle":item.get("candle"),"features":{k:features[k] for k in names if k in features}}
    quotes=market.get("quotes",{})
    # Only scalar quote metadata, not depth arrays or trade samples.
    out_quotes={k:({a:b for a,b in v.items() if type(b) in (str,int,float,bool) or b is None}
                   if isinstance(v,dict) else None) for k,v in quotes.items()}
    return {**context,"market":{"frames":frames,"context":market.get("context",{}),"quotes":out_quotes}}
