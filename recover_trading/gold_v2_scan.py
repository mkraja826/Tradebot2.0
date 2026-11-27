"""Standalone XAUTUSD V2 observation path; no legacy signal or broker writes."""
import argparse
import json
import time
from tradebot.market_data_v3 import collect, public_client
from .gold_v2_engine import Bar, evaluate

FRAME_MAP = {"5m": 300, "15m": 900, "1h": 3600}

def scan(client, as_of, *, collector=collect):
    raw = collector(client, "XAUTUSD", as_of=as_of,
                    frames=tuple(FRAME_MAP), count=250)
    if raw.get("symbol") != "XAUTUSD" or raw.get("as_of") != as_of:
        raise ValueError("wrong_market_or_cutoff")
    frames = {}
    health = {}
    for key, seconds in FRAME_MAP.items():
        item = raw["frames"].get(key, {})
        health[key] = item.get("status", "unavailable")
        if item.get("status") == "ready":
            frames[seconds] = [Bar(
                b["time"]+seconds,b["open"],b["high"],b["low"],
                b["close"],b["volume"]) for b in item["bars"]]
    return dict(evaluate(frames,as_of), feed_health=health)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once",action="store_true",required=True)
    parser.parse_args()
    print(json.dumps(scan(public_client(),int(time.time())),allow_nan=False))

if __name__=="__main__":
    main()
