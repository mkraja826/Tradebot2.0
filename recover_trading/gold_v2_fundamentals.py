"""Point-in-time Gold V2 external context; descriptive hypotheses only."""
from datetime import datetime, timezone
from math import isfinite
from tradebot.gold_macro_v3 import features as published_macro
from tradebot.news_context_v3 import parse as parse_news, URLS
from recover_trading.macro_feed import collect_context, fetch
from tradebot.gold_reference_v3 import collect as collect_spot
from .gold_v2_fed_fallback import apply_fallback

def number(v):
    return type(v) in (int,float) and isfinite(v)

def fresh(item, now, ttl):
    return (isinstance(item,dict) and item.get("status")=="ready"
            and number(item.get("observed_at"))
            and 0<=now-item["observed_at"]<=ttl)

def recent_event(item, key, now):
    if not fresh(item,now,420):
        return {"status":"unavailable"}
    d=item.get("data",{})
    is_fomc=key=="fomc_release"
    if d.get("source")!=("federal_reserve_monetary_rss" if is_fomc else "bls_official_atom"):
        return {"status":"unavailable"}
    try:
        stamp=datetime.fromisoformat(d["published_at" if is_fomc else "feed_timestamp"])
        if stamp.tzinfo is None or stamp.timestamp()>item["observed_at"]:
            raise ValueError("invalid_time")
        age=now-stamp.timestamp()
    except (KeyError,ValueError,TypeError):
        return {"status":"unavailable"}
    return {"status":"observed","published_or_feed_at":stamp.isoformat(),
            "recent_45m":0<=age<=2700,
            "release_time_verified":is_fomc,
            "consensus_surprise":None}

def context(refs, spot, *, as_of, delta_close=None, delta_closed_at=None):
    if not number(as_of):
        raise ValueError("invalid_cutoff")
    # Reuse validated publication feature extraction, not legacy signal rules.
    macro,official_sources=apply_fallback(published_macro(refs,observed_at=as_of),refs,as_of)
    dollar=macro["broad_dollar_5obs_pct"]
    real=macro["real_yield_5obs_bp"]
    # Initial descriptive bands, not learned weights or entry requirements.
    def vote(v, threshold):
        return None if v is None else -1 if v>threshold else 1 if v<-threshold else 0
    votes={"broad_dollar":vote(dollar,0.2),"real_yield":vote(real,5)}
    if any(v is None for v in votes.values()):
        bias="unknown"
    elif votes["broad_dollar"]==votes["real_yield"]==1:
        bias="gold_supportive"
    elif votes["broad_dollar"]==votes["real_yield"]==-1:
        bias="gold_adverse"
    else:
        bias="mixed_or_flat"
    reference={"status":"unavailable","basis_bps":None}
    try:
        observed=spot["timestamp_us"]/1e6
        updated=spot["provider_updated_us"]/1e6
        price=float(spot["price_usd_per_troy_ounce"])
        if (spot["source"]=="gold_api_indicative_spot" and spot["symbol"]=="XAU"
                and spot["currency"]=="USD" and number(price) and price>0
                and 0<=as_of-observed<=90 and 0<=observed-updated<=60):
            reference={"status":"observed","spot_usd":price,"observed_at":observed,
                       "provider_updated_at":updated,"basis_bps":None,
                       "executable":False}
            if (number(delta_close) and delta_close>0 and number(delta_closed_at)
                    and 0<=as_of-delta_closed_at<=90 and abs(delta_closed_at-updated)<=60):
                reference["basis_bps"]=10000*(delta_close/price-1)
    except (KeyError,TypeError,ValueError,OverflowError):
        pass
    return {"as_of":as_of,"execution_effect":"none","macro":macro,
            "macro_frequency":"published_daily_not_intraday_dxy",
            "macro_bias_hypothesis":bias,"votes":votes,
            "sources":{k:{"observed_at":refs[k]["observed_at"],
                        "source":refs[k].get("source")}
                       for k in ("broad_dollar","yields") if fresh(refs.get(k),as_of,22200)} | official_sources,
            "spot_reference":reference,
            "events":{k:recent_event(refs.get(k),k,as_of)
                      for k in ("fomc_release","cpi_release","nfp_release")},
            "not_integrated":["intraday_dxy","comex","etf_flows","central_bank_purchases",
                              "geopolitics","futures_positioning","consensus_forecasts"]}

def collect_external(*, macro_collector=collect_context, spot_collector=collect_spot,
                     reader=fetch, clock=lambda:datetime.now(timezone.utc)):
    """Live read-only collection. Inject providers for offline tests."""
    try:
        refs=macro_collector()
    except Exception:
        refs={}
    refs=dict(refs)
    for key in ("cpi_release","nfp_release"):
        try:
            raw=reader(URLS[key])
            now=clock()
            refs[key]={"status":"ready","observed_at":now.timestamp(),
                       "data":parse_news(raw,key,now)}
        except Exception:
            refs[key]={"status":"unavailable"}
    try:
        spot=spot_collector()
    except Exception:
        spot={}
    return refs,spot
