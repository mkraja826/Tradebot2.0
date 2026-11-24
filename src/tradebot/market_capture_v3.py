"""One-shot read-only research collector. No service or order activation."""
from concurrent.futures import ThreadPoolExecutor
from time import time
from pathlib import Path
import argparse
import json
from tradebot.market_data_v3 import collect,public_client,MARKETS,FRAMES
from tradebot.market_intelligence_v3 import collect_intelligence
from tradebot.market_store_v3 import MarketStore

def capture(path, *, now=None):
    stamp=int(time()) if now is None else now
    store=MarketStore(path)
    def market(symbol):
        client=public_client()
        output={}
        for frame in FRAMES:
            count=180 if symbol=="XAUTUSD" and frame=="1d" else 250
            data=collect(client,symbol,as_of=stamp,frames=[frame],count=count)["frames"][frame]
            result={"status":data["status"],"count":len(data["bars"]),"requested":count}
            if data["status"]=="ready":
                try: result["inserted"]=store.candles(symbol,frame,data["bars"],as_of=stamp)
                except (ValueError,OSError): result["status"]="store_rejected"
            else: result["reason"]=data.get("reason")
            output[frame]=result
        for kind,item in collect_intelligence(client,symbol).items():
            result={"status":item["status"]}
            if item["status"]=="ready":
                try: result["inserted"]=store.intelligence(symbol,kind,item["data"])
                except (ValueError,OSError): result["status"]="store_rejected"
            output[kind]=result
        return symbol,output
    with ThreadPoolExecutor(max_workers=2) as pool:
        markets=dict(pool.map(market,MARKETS))
    return {"mode":"read_only_research","as_of":stamp,"markets":markets,
            "stored_observations":sum(x[2] for x in store.counts())}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--database",type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(capture(a.database),sort_keys=True))

if __name__=="__main__":
    main()
