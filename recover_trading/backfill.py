"""Public historical candle backfill into a separate research database."""
import argparse
import json
import time
from pathlib import Path
from tradebot.market_data_v3 import MARKETS,FRAMES,collect,public_client
from tradebot.market_store_v3 import MarketStore

def backfill(store,client,symbol,start,end,frames,*,pause=0.15):
    if start>=end or end>int(time.time()) or start<=0:
        raise ValueError("invalid historical range")
    results=[]
    for frame in frames:
        step=FRAMES[frame]
        # Earlier completed windows are needed for the exact production indicators.
        warmup=900 if frame=="5m" else 250
        first=start//step*step-warmup*step
        cutoff=end//step*step
        for a in range(first,cutoff,250*step):
            b=min(a+250*step,cutoff)
            count=(b-a)//step
            item=collect(client,symbol,as_of=b,frames=(frame,),count=count)["frames"][frame]
            status=item["status"]; inserted=0
            if status=="ready":
                try: inserted=store.candles(symbol,frame,item["bars"],as_of=b)
                except ValueError: status="conflicting_observation"
            results.append({"frame":frame,"start":a,"end":b,"status":status,"inserted":inserted})
            if pause: time.sleep(pause)
    return results

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",required=True)
    p.add_argument("--symbol",required=True,choices=MARKETS)
    p.add_argument("--start",required=True,type=int)
    p.add_argument("--end",required=True,type=int)
    p.add_argument("--frames",nargs="+",choices=tuple(FRAMES),default=list(FRAMES))
    a=p.parse_args()
    path=Path(a.database)
    if path.name!="historical.sqlite":
        p.error("use a separate historical.sqlite research database")
    results=backfill(MarketStore(path),public_client(),a.symbol,a.start,a.end,a.frames)
    print(json.dumps({"symbol":a.symbol,"windows":len(results),"ready":sum(x["status"]=="ready" for x in results),"inserted":sum(x["inserted"] for x in results),"failed":[x for x in results if x["status"]!="ready"]}))

if __name__=="__main__":
    main()
