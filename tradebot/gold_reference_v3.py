"""Indicative independent XAU/USD spot reference, not an executable quote."""
from datetime import datetime
from time import time
from urllib.request import Request,urlopen
import json
from math import isfinite
from tradebot.market_intelligence_v3 import number

URL="https://api.gold-api.com/price/XAU"

def parse(raw,*,observed_us):
    if type(observed_us) is not int or observed_us<=0: raise ValueError("invalid_time")
    d=json.loads(raw)
    if d.get("symbol")!="XAU" or d.get("currency")!="USD": raise ValueError("wrong_reference")
    stamp=datetime.fromisoformat(d["updatedAt"])
    if stamp.tzinfo is None: raise ValueError("missing_timezone")
    updated=int(stamp.timestamp()*1e6)
    if not 0<=observed_us-updated<=60_000_000: raise ValueError("stale_reference")
    return {"source":"gold_api_indicative_spot","timestamp_us":observed_us,
        "provider_updated_us":updated,"price_usd_per_troy_ounce":number(d["price"],positive=True),
        "symbol":"XAU","currency":"USD","exchange_trade_timestamp_verified":False,
        "executable_spread_available":False}

def collect():
    with urlopen(Request(URL,headers={"User-Agent":"Tradebot research/3.0"}),timeout=6) as r:
        raw=r.read(100001)
    if len(raw)>100000: raise ValueError("oversize")
    return parse(raw,observed_us=int(time()*1e6))

def features(quotes,*,as_of):
    out={"indicative_gold_basis_bps":None,"delta_quote_spread_bps":None}
    try:
        r=quotes["xau_reference"]; t=quotes["ticker"]; now=as_of*1e6
        if r["source"]!="gold_api_indicative_spot" or r["symbol"]!="XAU" or r["currency"]!="USD" or t["source"]!="delta_demo_ticker": return out
        if not 0<=now-r["timestamp_us"]<=90_000_000 or not 0<=now-t["timestamp_us"]<=90_000_000: return out
        if not 0<=r["timestamp_us"]-r["provider_updated_us"]<=60_000_000 or abs(t["timestamp_us"]-r["provider_updated_us"])>60_000_000: return out
        bid=number(t["bid"],positive=True); ask=number(t["ask"],positive=True)
        if bid>=ask: return out
        mid=(bid+ask)/2; spot=number(r["price_usd_per_troy_ounce"],positive=True)
        return {"indicative_gold_basis_bps":10000*(mid/spot-1),"delta_quote_spread_bps":10000*(ask-bid)/mid}
    except (KeyError,TypeError,ValueError,OverflowError): return out
