"""Public Delta demo ticker and L2 intelligence. Raw funding/OI units preserved."""
from math import isfinite
from time import time
from tradebot.market_data_v3 import MARKETS
from tradebot.delta import DEMO_API

def number(value, *, positive=False):
    if isinstance(value,bool): raise ValueError("invalid_number")
    try: x=float(value)
    except (TypeError,ValueError,OverflowError): raise ValueError("invalid_number") from None
    if not isfinite(x) or (positive and x<=0): raise ValueError("invalid_number")
    return x

def timestamp(row,key,now):
    t=row.get(key)
    if type(t) is not int or not 0 <= now*1_000_000-t <= 60_000_000:
        raise ValueError("stale_or_invalid_timestamp")
    return t

def identity(row,symbol):
    if not isinstance(row,dict) or symbol not in MARKETS or row.get("symbol")!=symbol:
        raise ValueError("invalid_symbol")

def ticker_features(row,symbol,now):
    identity(row,symbol)
    t=timestamp(row,"timestamp",now)
    q=row.get("quotes")
    if not isinstance(q,dict): raise ValueError("invalid_quotes")
    b,a=(number(q.get(k),positive=True) for k in ("best_bid","best_ask"))
    if b>=a: raise ValueError("crossed_book")
    mark,spot=(number(row.get(k),positive=True) for k in ("mark_price","spot_price"))
    oi=number(row.get("oi"))
    if oi<0: raise ValueError("invalid_open_interest")
    return {"timestamp_us":t,"bid":b,"ask":a,"spread_bps":(a-b)/((a+b)/2)*10000,
            "mark":mark,"spot_reference":spot,"mark_spot_basis_bps":(mark/spot-1)*10000,
            "open_interest_raw":oi,"funding_rate_raw":number(row.get("funding_rate")),
            "source":"delta_demo_ticker"}

def book_features(row,symbol,now):
    identity(row,symbol)
    t=timestamp(row,"last_updated_at",now)
    def levels(key,reverse):
        raw=row.get(key)
        if not isinstance(raw,list) or not 1<=len(raw)<=20: raise ValueError("invalid_depth")
        if any(not isinstance(x,dict) for x in raw): raise ValueError("invalid_level")
        data=[(number(x.get("price"),positive=True),number(x.get("size"),positive=True)) for x in raw]
        p=[x[0] for x in data]
        if len(set(p))!=len(p) or p!=sorted(p,reverse=reverse): raise ValueError("invalid_level_order")
        return data
    b,a=levels("buy",True),levels("sell",False)
    if b[0][0]>=a[0][0]: raise ValueError("crossed_book")
    n=min(len(b),len(a))
    buy=sum(x[1] for x in b[:n]); sell=sum(x[1] for x in a[:n])
    total=buy+sell
    if not isfinite(total): raise ValueError("invalid_depth_total")
    return {"timestamp_us":t,"levels_each":n,"bid_size":buy,"ask_size":sell,
            "imbalance":(buy-sell)/total,"bid":b[0][0],"ask":a[0][0],
            "spread_bps":(a[0][0]-b[0][0])/((a[0][0]+b[0][0])/2)*10000,
            "source":"delta_demo_l2"}

def collect_intelligence(client,symbol):
    if symbol not in MARKETS or getattr(client,"base_url",None)!=DEMO_API or getattr(client,"allow_orders",None) is not False:
        raise ValueError("read_only_demo_market_required")
    result={}
    for name in ("ticker","book"):
        try:
            if name=="ticker":
                row=client.ticker(symbol); data=ticker_features(row,symbol,time())
            else:
                row=client._request("GET","/v2/l2orderbook/"+symbol,params={"depth":20})["result"]
                data=book_features(row,symbol,time())
            result[name]={"status":"ready","data":data}
        except Exception:
            result[name]={"status":"unavailable","data":None}
    return result
