"""Standalone XAUTUSD V2 observation path; no legacy signal or broker writes."""
import argparse
import json
import time
from tradebot.market_data_v3 import collect, public_client
from .gold_v2_engine import Bar, evaluate
from .gold_v2_fundamentals import context, collect_external
from .gold_v2_public_feeds import PublicFeeds, feature_packet

FRAME_MAP = {"5m": 300, "15m": 900, "1h": 3600}

def scan(client, as_of, *, collector=collect, external=None, public_feeds=None, clock=time.time):
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
    result = dict(evaluate(frames,as_of), feed_health=health)
    if external is not None or public_feeds is not None:
        refs, spot = external() if external is not None else ({},{})
        items = public_feeds.collect() if public_feeds is not None else {}
        cutoff = max(as_of, clock())
        if public_feeds is not None:
            result["public_feeds"] = feature_packet(items,cutoff)
        last = frames[300][-1] if frames.get(300) else None
        result["fundamentals"] = context(refs, spot, as_of=cutoff,
            delta_close=last.c if last else None,
            delta_closed_at=last.ts if last else None)
        result["decision_as_of"] = cutoff
        result["external_context"] = "descriptive_only"
        if int(cutoff)//300 != as_of//300:
            result["status"] = "candle_boundary_crossed"
            result["candidates"] = []
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once",action="store_true",required=True)
    parser.add_argument("--fundamentals", action="store_true")
    parser.add_argument("--public-feeds", action="store_true")
    args = parser.parse_args()
    print(json.dumps(scan(public_client(),int(time.time()),
                          external=collect_external if args.fundamentals else None,
                          public_feeds=PublicFeeds() if args.public_feeds else None),allow_nan=False))

if __name__=="__main__":
    main()
