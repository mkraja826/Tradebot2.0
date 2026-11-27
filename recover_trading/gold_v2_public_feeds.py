"""Keyless public Gold V2 feeds. Read-only, source-specific and timestamped."""
from datetime import datetime, timezone, date, timedelta
from concurrent.futures import ThreadPoolExecutor
from math import isfinite
from urllib.parse import urlencode
import csv
import io
import json
import time
from .macro_feed import fetch

COT_URL="https://publicreporting.cftc.gov/resource/72hh-3qpy.json?"+urlencode({
    "cftc_contract_market_code":"088691","$order":"report_date_as_yyyy_mm_dd DESC","$limit":5})
XAUS_URL="https://xaus.com/api/v1/spot?compact=1"
GOLD_API="https://api.gold-api.com/price/"
BINANCE="https://data-api.binance.vision/api/v3/aggTrades?"
FRED="https://fred.stlouisfed.org/graph/fredgraph.csv?"
FRED_IDS=("DFF","T10YIE","VIXCLS","DCOILWTICO")
TTL={"xaus":30,"silver":60,"paxg_usdt":60,"xaut_usdt":60,"cot":21600,"macro_extra":21600}

def value(v,positive=False):
    if isinstance(v,bool):
        raise ValueError("invalid_value")
    x=float(v)
    if not isfinite(x) or positive and x<=0:
        raise ValueError("invalid_value")
    return x

def timestamp(s):
    t=datetime.fromisoformat(s.replace("Z","+00:00"))
    if t.tzinfo is None:
        raise ValueError("missing_timezone")
    return t.timestamp()

def check_age(t,now,limit):
    if not 0<=now-t<=limit:
        raise ValueError("stale_or_future")

def xaus(raw,now):
    d=json.loads(raw)
    if d["source"]!="xaus.com" or d["data_state"]["status"]!="fresh" or d.get("stale") is not False:
        raise ValueError("unusable_spot")
    t=timestamp(d["price_as_of"])
    check_age(t,now,120)
    out={"price_usd_oz":value(d["spot_usd_oz"],True),"price_as_of":t,
         "source":"xaus_aggregator","upstream_source":d.get("price_source"),
         "independent_of_gold_api":"not_established"}
    # Annual figures, not live central bank flows.
    if d.get("stats_as_of"):
        vintage=date.fromisoformat(d["stats_as_of"])
        if vintage<=datetime.fromtimestamp(now,timezone.utc).date():
            out["annual_stats"]={"vintage":vintage.isoformat(),
                **{k:value(d[k]) for k in ("cb_reserves_tonnes","cb_net_purchases_tonnes","gold_supply_tonnes")
                   if d.get(k) is not None}}
    return out

def silver(raw,now):
    d=json.loads(raw)
    if d["symbol"]!="XAG" or d["currency"]!="USD":
        raise ValueError("wrong_metal")
    t=timestamp(d["updatedAt"])
    check_age(t,now,90)
    return {"price_usd_oz":value(d["price"],True),"price_as_of":t,"source":"gold_api_xag"}

def token(raw,now,symbol):
    rows=json.loads(raw)
    if not isinstance(rows,list) or len(rows)!=1:
        raise ValueError("unexpected_trade_count")
    d=rows[0];t=value(d["T"])/1000
    check_age(t,now,120)
    return {"symbol":symbol,"price_usdt":value(d["p"],True),"price_as_of":t,
            "source":"binance_public_agg_trade","instrument":"tokenized_gold_not_xauusd"}

def cot(raw,now):
    rows=json.loads(raw)
    if not isinstance(rows,list) or len(rows)<2:
        raise ValueError("insufficient_cot")
    parsed=[]
    today=datetime.fromtimestamp(now,timezone.utc).date()
    for r in rows:
        if r["cftc_contract_market_code"]!="088691":
            raise ValueError("wrong_market")
        day=date.fromisoformat(r["report_date_as_yyyy_mm_dd"][:10])
        oi=value(r["open_interest_all"],True)
        long=value(r["m_money_positions_long_all"])
        short=value(r["m_money_positions_short_all"])
        if day>today or min(long,short)<0 or max(long,short)>oi:
            raise ValueError("invalid_cot")
        parsed.append((day,long-short,oi))
    if any(a[0]<=b[0] for a,b in zip(parsed,parsed[1:])):
        raise ValueError("invalid_report_order")
    day,net,oi=parsed[0]
    if (today-day).days>21:
        raise ValueError("stale_cot")
    return {"source":"cftc_disaggregated_futures_only","report_date":day.isoformat(),
            "observed_at":now,"managed_money_net_contracts":net,
            "managed_money_net_change":net-parsed[1][1],
            "open_interest_contracts":oi,"managed_money_net_share":net/oi,
            "release_timestamp":"not_verified","frequency":"weekly"}

def macro_extra(raw,now):
    today=datetime.fromtimestamp(now,timezone.utc).date()
    series={k:{} for k in FRED_IDS}
    for row in csv.DictReader(io.StringIO(raw)):
        day=date.fromisoformat(row["observation_date"])
        if day>=today:
            continue
        for k,days in series.items():
            v=row.get(k)
            if v in (None,"","."):
                continue
            x=value(v)
            if day in days and days[day]!=x:
                raise ValueError("conflicting_values")
            days[day]=x
    out={}
    for k,days in series.items():
        dates=sorted(days)
        if len(dates)>=6 and (today-dates[-1]).days<=10 and (dates[-1]-dates[-6]).days<=14:
            out[k]={"latest":days[dates[-1]],"date":dates[-1].isoformat(),
                    "change_5_observations":days[dates[-1]]-days[dates[-6]]}
        else:
            out[k]=None
    return {"source":"fred_csv_as_observed","series":out,"frequency":"daily",
            "historical_vintage_verified":False}

class PublicFeeds:
    """Per-process caching; failures are explicit; no stale fallback as fresh."""
    def __init__(self,reader=fetch,clock=time.time):
        self.reader=reader
        self.clock=clock
        self.cache={}
    def collect(self):
        start=self.clock()
        from_date=(datetime.fromtimestamp(start,timezone.utc).date()-timedelta(days=45)).isoformat()
        tasks={"xaus":(XAUS_URL,xaus),
               "silver":(GOLD_API+"XAG",silver),
               "paxg_usdt":(BINANCE+urlencode({"symbol":"PAXGUSDT","limit":1}),lambda r,t:token(r,t,"PAXGUSDT")),
               "xaut_usdt":(BINANCE+urlencode({"symbol":"XAUTUSDT","limit":1}),lambda r,t:token(r,t,"XAUTUSDT")),
               "cot":(COT_URL,cot),
               "macro_extra":(FRED+urlencode({"id":",".join(FRED_IDS),"cosd":from_date}),macro_extra)}
        def one(key):
            cached=self.cache.get(key)
            # A transient error must not suppress slow feeds for six hours.
            ttl=TTL[key] if cached and cached.get("status")=="observed" else min(TTL[key],60)
            if cached and 0<=start-cached["observed_at"]<ttl:
                return key,cached
            url,parser=tasks[key]
            try:
                raw=self.reader(url);now=self.clock()
                item={"status":"observed","observed_at":now,"data":parser(raw,now)}
            except Exception as exc:
                item={"status":"unavailable","observed_at":self.clock(),"reason":type(exc).__name__}
            return key,item
        with ThreadPoolExecutor(max_workers=4) as pool:
            result=dict(pool.map(one,tasks))
        self.cache.update(result)
        return result

def feature_packet(items,now):
    """Retain provenance and reject expired observations at decision time."""
    out={}
    for key,ttl in TTL.items():
        item=items.get(key,{})
        try:
            check_age(item["observed_at"],now,ttl)
            if item.get("status")!="observed":
                raise ValueError("unavailable")
            d=item["data"]
            if "price_as_of" in d:
                check_age(d["price_as_of"],now,90 if key=="silver" else 120)
            out[key]=item
        except (KeyError,TypeError,ValueError):
            out[key]={"status":"unavailable_or_stale"}
    gold=out["xaus"].get("data",{});ag=out["silver"].get("data",{})
    ratio=None
    if gold and ag and abs(gold["price_as_of"]-ag["price_as_of"])<=60:
        ratio=gold["price_usd_oz"]/ag["price_usd_oz"]
    return {"execution_effect":"none","feeds":out,"gold_silver_ratio":ratio,
            "token_prices_quote_currency":"USDT_not_USD","as_of":now}
