"""Bounded public recent-trade samples, not complete interval trade flow."""
from time import time
from tradebot.market_intelligence_v3 import number
from tradebot.market_data_v3 import MARKETS
from tradebot.delta import DEMO_API

def project(raw,symbol,now_us):
    if symbol not in MARKETS or not isinstance(raw,list) or not 20<=len(raw)<=1000:
        raise ValueError("invalid_sample")
    sizes={"buy":0.,"sell":0.}; stamps=[]
    for r in raw:
        if r.get("symbol")!=symbol: raise ValueError("wrong_symbol")
        t=r.get("timestamp")
        if type(t) is not int or not 0<=now_us-t<=300_000_000: raise ValueError("stale_trade")
        roles=(r.get("buyer_role"),r.get("seller_role"))
        if roles==("taker","maker"): side="buy"
        elif roles==("maker","taker"): side="sell"
        else: raise ValueError("unknown_aggressor")
        number(r.get("price"),positive=True)
        sizes[side]+=number(r.get("size"),positive=True); stamps.append(t)
    if now_us-max(stamps)>30_000_000 or max(stamps)==min(stamps): raise ValueError("stale_or_zero_span")
    total=number(sum(sizes.values()),positive=True)
    return {"symbol":symbol,"source":"delta_demo_recent_trade_sample","timestamp_us":now_us,
        "newest_trade_us":max(stamps),"oldest_trade_us":min(stamps),"sample_count":len(raw),
        "sample_imbalance":(sizes["buy"]-sizes["sell"])/total,"complete_interval":False}

def collect_flow(client,symbol):
    if client.base_url!=DEMO_API or client.allow_orders is not False: raise ValueError("readonly_demo_required")
    raw=client._request("GET","/v2/trades/"+symbol)["result"]
    return project(raw,symbol,int(time()*1e6))

def inputs(quotes):
    f=quotes.get("flow"); b=quotes.get("book")
    if not f or not b: return {}
    if abs(f["timestamp_us"]-b["timestamp_us"])>60_000_000 or f["timestamp_us"]-f["newest_trade_us"]>30_000_000: return {}
    return {"sample_flow_imbalance":f["sample_imbalance"],"book_imbalance":b["imbalance"],"book_spread_bps":b["spread_bps"]}
