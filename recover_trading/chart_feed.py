"""Independent display-only public DEMO completed-candle cache.

Never writes to execution/strategy journals. No credentials, AI or order calls.
A missing bar does not invalidate the other observed bars.
"""
import argparse
import concurrent.futures
import json
import math
import os
from pathlib import Path
import time
import threading
from .chart_quote import quote_loop

from tradebot.market_data_v3 import MARKETS, FRAMES, public_client

COUNT = 350
SOURCE = "demo_public_completed_candles"
REFERENCE_SOURCE = "reference_public_completed_candles"
FIELDS = ("open", "high", "low", "close", "volume")


def validated(rows, frame, end):
    """Keep individually valid, aligned, unique completed bars; reject duplicate timestamps."""
    step = FRAMES[frame]
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("invalid response")
    bars, duplicate, invalid = {}, set(), 0
    for row in rows:
        t = row.get("time") if isinstance(row, dict) else None
        if type(t) is not int:
            invalid += 1
            continue
        if t < end - COUNT * step or t >= end:
            continue
        if t % step:
            invalid += 1
            continue
        if t in bars or t in duplicate:
            bars.pop(t, None)
            duplicate.add(t)
            invalid += 1
            continue
        try:
            if any(isinstance(row[k], bool) for k in FIELDS):
                raise ValueError()
            o, h, l, c, v = (float(row[k]) for k in FIELDS)
            if not all(map(math.isfinite, (o,h,l,c,v))) or not 0 < l <= min(o,c) <= max(o,c) <= h or v < 0:
                raise ValueError()
        except (ValueError, TypeError, KeyError, OverflowError):
            invalid += 1
            duplicate.add(t)
            continue
        bars[t] = dict(zip(("time",) + FIELDS, (t,o,h,l,c,v)))
    return [bars[t] for t in sorted(bars)], invalid


def cache_path(directory, symbol, frame):
    if symbol not in MARKETS or frame not in FRAMES:
        raise ValueError("invalid selection")
    return Path(directory) / (symbol + "-" + frame + ".json")


def read_cache(directory, symbol, frame, now, *, source=SOURCE):
    if not directory:
        return None
    try:
        p = cache_path(directory, symbol, frame)
        with p.open("rb") as f:
            raw = f.read(1_000_001)
        if len(raw) > 1_000_000:
            return None
        data = json.loads(raw)
        end = data["boundary"]
        observed = data["observed_at"]
        if (data.get("source") != source or data.get("symbol") != symbol or
            data.get("frame") != frame or type(end) is not int or
            type(observed) is not int or not 0 < end <= observed <= now or
            end % FRAMES[frame] or observed - end >= FRAMES[frame]):
            return None
        rows, bad = validated(data["candles"], frame, end)
        if not rows or bad or type(data["invalid_rows"]) is not int or data["invalid_rows"] < 0:
            return None
        return {**data, "candles": rows}
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return None


def refresh(directory, symbol, frame, now, client_factory=public_client, *, source=SOURCE):
    step = FRAMES[frame]
    end = now // step * step
    rows = client_factory().candles(symbol=symbol, resolution=frame,
                                     start=end - COUNT * step, end=end)
    candles, invalid = validated(rows, frame, end)
    if not candles:
        raise ValueError("empty validated candle window")
    old = read_cache(directory, symbol, frame, now, source=source)
    # Never replace a more recent successful window with an older response.
    if old and candles[-1]["time"] < old["candles"][-1]["time"]:
        return old
    data = {"source": source, "symbol": symbol, "frame": frame,
            "boundary": end, "observed_at": now, "candles": candles,
            "invalid_rows": invalid}
    path = cache_path(directory, symbol, frame)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    return data


def collect(directory, once=False, reference=False):
    from .chart_reference import ReferenceClient
    from .chart_quote import REFERENCE_SOURCE as REFERENCE_QUOTE_SOURCE, SOURCE as DEMO_QUOTE_SOURCE
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    factory=ReferenceClient if reference else public_client
    source=REFERENCE_SOURCE if reference else SOURCE
    quote_source=REFERENCE_QUOTE_SOURCE if reference else DEMO_QUOTE_SOURCE
    if not once:
        threading.Thread(target=quote_loop,args=(directory,threading.Event()),kwargs={"client_factory":factory,"source":quote_source},daemon=True,name="display-quotes").start()
    last_attempt = {}
    pairs = [(s,f) for s in MARKETS for f in FRAMES]
    while True:
        now = int(time.time())
        due = []
        for s, f in pairs:
            end = now // FRAMES[f] * FRAMES[f]
            previous = read_cache(directory,s,f,now,source=source)
            complete = previous and previous["candles"][-1]["time"] == end - FRAMES[f]
            if once or (not complete and now - end >= 3 and now - last_attempt.get((s,f),0) >= 30):
                due.append((s,f))
                last_attempt[s,f] = now
        def task(pair):
            s,f = pair
            try:
                data = refresh(directory,s,f,int(time.time()),factory,source=source)
                print(source,s,f,"bars",len(data["candles"]),"last",data["candles"][-1]["time"],flush=True)
            except Exception as exc:
                print(source,s,f,"unavailable",type(exc).__name__,flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(task,due))
        if once:
            return
        time.sleep(5)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache-dir",required=True)
    p.add_argument("--once",action="store_true")
    p.add_argument("--reference",action="store_true")
    args=p.parse_args()
    collect(args.cache_dir,args.once,args.reference)

if __name__ == "__main__":
    main()
