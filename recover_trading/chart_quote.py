"""Display-only public demo ticker snapshots. No synthetic candles."""
import json
import math
import os
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor
from tradebot.market_data_v3 import MARKETS, public_client

SOURCE = "demo_public_ticker"
REFERENCE_SOURCE = "reference_public_ticker"
MAX_AGE_S = 15
POLL_S = 3

def path_for(directory,symbol):
    if symbol not in MARKETS:
        raise ValueError("invalid symbol")
    return Path(directory)/(symbol+"-quote.json")

def positive(v):
    if isinstance(v,bool):
        raise ValueError("invalid price")
    n=float(v)
    if not math.isfinite(n) or n<=0:
        raise ValueError("invalid price")
    return n

def normalize(symbol,raw,now,*,source=SOURCE):
    if symbol not in MARKETS or not isinstance(raw,dict) or raw.get("symbol")!=symbol:
        raise ValueError("ticker identity mismatch")
    t=raw.get("timestamp")
    if type(t) is not int or not 0<t<=int((now+2)*1_000_000):
        raise ValueError("invalid exchange timestamp")
    return {"symbol":symbol,"source":source,"exchange_time_us":t,"observed_at":now,
            "last_price":positive(raw["close"]),"mark_price":positive(raw["mark_price"])}

def read_quote(directory,symbol,now,*,source=SOURCE):
    empty={"symbol":symbol,"source":source,"status":"unavailable","last_price":None,"mark_price":None,"exchange_time_us":None,"observed_at":None,"age_s":None,"generated":now}
    if not directory:
        return empty
    try:
        with path_for(directory,symbol).open("rb") as f:
            raw=f.read(4097)
        if len(raw)>4096:
            return empty
        q=json.loads(raw)
        t=q["exchange_time_us"]; observed=q["observed_at"]
        if q.get("symbol")!=symbol or q.get("source")!=source or type(t) is not int or type(observed) is not int or not 0<observed<=now or not 0<t<=int((observed+2)*1_000_000):
            return empty
        age=round(now-t/1_000_000,3)
        return {**empty,"status":"observed" if -2<=age<=MAX_AGE_S else "stale","last_price":positive(q["last_price"]),"mark_price":positive(q["mark_price"]),"exchange_time_us":t,"observed_at":observed,"age_s":age}
    except (OSError,ValueError,TypeError,KeyError,OverflowError):
        return empty

def refresh_quote(directory,symbol,client_factory=public_client,clock=time.time,*,source=SOURCE):
    raw=client_factory().ticker(symbol)
    now=int(clock())
    data=normalize(symbol,raw,now,source=source)
    old=read_quote(directory,symbol,now,source=source)
    if old["exchange_time_us"] is not None and old["exchange_time_us"]>=data["exchange_time_us"]:
        return old
    path=path_for(directory,symbol);tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data,allow_nan=False,separators=(",",":")),encoding="utf-8")
    os.replace(tmp,path)
    return data

def quote_loop(directory,stop,*,client_factory=public_client,source=SOURCE):
    def task(symbol):
        try:refresh_quote(directory,symbol,client_factory,source=source)
        except Exception:pass  # Retained observation ages naturally; no invented quote.
    with ThreadPoolExecutor(max_workers=2) as pool:
        while not stop.is_set():
            started=time.monotonic()
            list(pool.map(task,MARKETS))
            stop.wait(max(0.2,POLL_S-(time.monotonic()-started)))
