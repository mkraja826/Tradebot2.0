"""One-shot prospective Gold V2 research cycle using public demo data only."""
import argparse
import json
import time
from tradebot.market_data_v3 import collect,public_client
from .gold_v2_engine import Bar
from .gold_v2_scan import scan
from .gold_v2_fundamentals import collect_external
from .gold_v2_public_feeds import PublicFeeds
from .gold_v2_validation import Journal

def cycle(journal,client,*,clock=time.time,scanner=scan,collector=collect,
          external=None,public_feeds=None):
    report=scanner(client,int(clock()),external=external,public_feeds=public_feeds,clock=clock)
    try:
        enrollment=journal.enroll(report)
    except ValueError as exc:
        enrollment={"status":"not_enrolled","reason":str(exc)}
    stamp=int(clock())
    raw=collector(client,"XAUTUSD",as_of=stamp,frames=("5m",),count=400)
    if raw.get("symbol")!="XAUTUSD" or raw.get("as_of")!=stamp:
        raise ValueError("wrong_resolution_market_or_cutoff")
    item=raw["frames"].get("5m",{})
    resolved=None
    if item.get("status")=="ready":
        bars=[Bar(b["time"]+300,b["open"],b["high"],b["low"],b["close"],b["volume"]) for b in item["bars"]]
        resolved=journal.resolve(bars)
    return {"symbol":"XAUTUSD","execution_effect":"none","enrollment":enrollment,
            "resolution_feed":item.get("status","unavailable"),"resolved_windows":resolved,
            "validation":journal.summary()}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal",required=True)
    parser.add_argument("--summary",action="store_true")
    parser.add_argument("--fundamentals",action="store_true")
    parser.add_argument("--public-feeds",action="store_true")
    args=parser.parse_args()
    journal=Journal(args.journal)
    try:
        result=journal.summary() if args.summary else cycle(journal,public_client(),
                    external=collect_external if args.fundamentals else None,
                    public_feeds=PublicFeeds() if args.public_feeds else None)
        print(json.dumps(result,allow_nan=False))
    finally:
        journal.close()
if __name__=="__main__":
    main()
