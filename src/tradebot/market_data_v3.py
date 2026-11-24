"""Tradebot3 read-only multi-timeframe market data; no AI or order calls."""
from math import isfinite
from time import time
from tradebot.delta import DeltaDemo, DEMO_API

MARKETS = ("BTCUSD", "XAUTUSD")
FRAMES = {"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,
          "1h":3600,"4h":14400,"1d":86400}
FIELDS = ("open","high","low","close","volume")


def normalize(rows, frame, *, as_of, count=250):
    """Only exact, consecutive completed UTC candles; no gap filling."""
    step = FRAMES[frame]
    if type(as_of) is not int or type(count) is not int or not 1 <= count <= 1900:
        raise ValueError("invalid_window")
    boundary = as_of // step * step
    start = boundary - step * count
    if start <= 0 or not isinstance(rows, list):
        raise ValueError("invalid_window_or_response")
    bars = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("time")) is not int:
            raise ValueError("invalid_timestamp")
        t = row["time"]
        if t < start or t >= boundary:
            continue
        if t % step or t in bars:
            raise ValueError("misaligned_or_duplicate_candle")
        try:
            if any(isinstance(row[k], bool) for k in FIELDS):
                raise ValueError()
            o,h,l,c,v = (float(row[k]) for k in FIELDS)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("invalid_ohlcv") from None
        if not all(map(isfinite,(o,h,l,c,v))) or not 0 < l <= min(o,c) <= max(o,c) <= h or v < 0:
            raise ValueError("invalid_ohlcv")
        bars[t] = dict(zip(("time",)+FIELDS,(t,o,h,l,c,v)))
    expected = range(start,boundary,step)
    if len(bars) != count or any(t not in bars for t in expected):
        raise ValueError("missing_or_stale_candles")
    return [bars[t] for t in expected]


def collect(client, symbol, *, as_of=None, frames=None, count=250):
    """A feed failure disables only that frame, never substitutes other data."""
    if symbol not in MARKETS or getattr(client,"base_url",None) != DEMO_API or getattr(client,"allow_orders",None) is not False:
        raise ValueError("read_only_demo_market_required")
    stamp = int(time()) if as_of is None else as_of
    if type(stamp) is not int or type(count) is not int or not 1 <= count <= 1900:
        raise ValueError("invalid_window")
    frames = tuple(FRAMES) if frames is None else tuple(frames)
    if not frames or len(set(frames)) != len(frames) or any(f not in FRAMES for f in frames):
        raise ValueError("invalid_frames")
    output = {}
    for frame in frames:
        step = FRAMES[frame]
        end = stamp // step * step
        try:
            rows = client.candles(symbol=symbol,resolution=frame,start=end-count*step,end=end)
            bars = normalize(rows,frame,as_of=stamp,count=count)
        except ValueError as exc:
            output[frame] = {"status":"unavailable","reason":str(exc) if str(exc) in {"invalid_timestamp","misaligned_or_duplicate_candle","invalid_ohlcv","missing_or_stale_candles","invalid_window_or_response"} else "invalid_feed","bars":[]}
        except Exception:
            output[frame] = {"status":"unavailable","reason":"feed_error","bars":[]}
        else:
            output[frame] = {"status":"ready","bars":bars,"last_closed_at":end}
    return {"symbol":symbol,"as_of":stamp,"frames":output}


def public_client():
    return DeltaDemo("", "", allow_orders=False)
