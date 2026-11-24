"""Incremental public research capture, independent from trading services."""
from pathlib import Path
from time import time
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import json,os,sqlite3,tempfile
from tradebot.market_data_v3 import collect,public_client,MARKETS,FRAMES
from tradebot.market_intelligence_v3 import collect_intelligence
from tradebot.market_store_v3 import MarketStore
from tradebot.trade_flow_v3 import collect_flow
from tradebot.derivative_context_v3 import SERIES,collect as derivative_collect
from tradebot.external_context_v3 import URLS,fetch,spot,daily,calendar
from tradebot.gold_macro_v3 import KEYS as MACRO_KEYS,history as macro_history
from tradebot.news_context_v3 import URLS as NEWS_URLS,parse as news_parse
from tradebot.gold_stress_v3 import URLS as STRESS_URLS,parse as stress_parse
from tradebot.gold_reference_v3 import collect as gold_reference

def atomic_json(path,obj):
    fd,name=tempfile.mkstemp(dir=path.parent,prefix=".capture-")
    try:
        with os.fdopen(fd,"w") as f: json.dump(obj,f,allow_nan=False,sort_keys=True)
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def refresh_external(root):
    path=root/"external-context.json"
    try: old=json.loads(path.read_text())
    except (OSError,ValueError): old={}
    def item(key):
        previous=old.get(key,{})
        interval=60 if key in ("btc_spot","gold_token_proxy") else 21600
        if key in NEWS_URLS: interval=300
        if previous.get("status")=="ready" and 0<=time()-previous.get("observed_at",0)<interval and (key not in MACRO_KEYS or "macro_history" in previous):
            return key,previous
        try:
            raw=fetch(key); now=datetime.now(timezone.utc)
            if key in ("btc_spot","gold_token_proxy"): data=spot(raw,now)
            elif key=="yields": data=daily(raw,("DGS10","DFII10"),now)
            elif key=="broad_dollar": data=daily(raw,("DTWEXBGS",),now)
            elif key in NEWS_URLS: data=news_parse(raw,key,now)
            elif key in STRESS_URLS: data=stress_parse(raw,key,now)
            else: data=calendar(raw,now)
            result={"status":"ready","observed_at":now.timestamp(),"data":data}
            if key in MACRO_KEYS:
                try: result["macro_history"]={"source":"fred_daily_as_observed","series":macro_history(raw,key,now)}
                except (ValueError,TypeError,KeyError): pass
            return key,result
        except Exception as exc: return key,{"status":"unavailable","reason":type(exc).__name__}
    with ThreadPoolExecutor(max_workers=3) as pool: out=dict(pool.map(item,URLS))
    atomic_json(path,out)
    return {k:v["status"] for k,v in out.items()}

def tick(root):
    root=Path(root); root.mkdir(mode=0o700,parents=True,exist_ok=True)
    store=MarketStore(root/"market-v3.sqlite")
    now=int(time())
    def market(symbol):
        c=public_client(); out={}
        for frame,step in FRAMES.items():
            expected=now//step*step-step
            prior=store.history(symbol,"candle:"+frame,1)
            if prior and prior[-1]["time"]==expected:
                out[frame]="cached_current"; continue
            count=180 if symbol=="XAUTUSD" and frame=="1d" else 250
            data=collect(c,symbol,as_of=now,frames=[frame],count=count)["frames"][frame]
            out[frame]=data["status"]
            if data["status"]=="ready":
                try: store.candles(symbol,frame,data["bars"],as_of=now)
                except (ValueError,sqlite3.Error): out[frame]="store_rejected"
        for kind,item in collect_intelligence(c,symbol).items():
            out[kind]=item["status"]
            if item["status"]=="ready":
                try: store.intelligence(symbol,kind,item["data"])
                except (ValueError,sqlite3.Error): out[kind]="store_rejected"
        try:
            store.intelligence(symbol,"flow",collect_flow(c,symbol)); out["flow"]="ready"
        except Exception: out["flow"]="unavailable"
        if symbol=="BTCUSD":
            for kind,(_,_,step,count) in SERIES.items():
                try:
                    old=store.history(symbol,kind,1)
                    if old and old[-1]["time"]==now//step*step-step: out[kind]="cached_current"; continue
                    rows=derivative_collect(c,kind,as_of=now)
                    if not rows: raise ValueError("missing_history")
                    store.derivative_history(kind,rows,as_of=now); out[kind]="ready"
                except Exception: out[kind]="unavailable"
        if symbol=="XAUTUSD":
            try: store.intelligence(symbol,"xau_reference",gold_reference()); out["xau_reference"]="ready"
            except Exception: out["xau_reference"]="unavailable"
        return symbol,out
    with ThreadPoolExecutor(max_workers=2) as pool: markets=dict(pool.map(market,MARKETS))
    out={"mode":"read_only_research","as_of":now,"markets":markets,
         "external":refresh_external(root),"stored":sum(x[2] for x in store.counts())}
    atomic_json(root/"collector-status.json",out)
    return out

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--directory",required=True,type=Path)
    print(json.dumps(tick(p.parse_args().directory),sort_keys=True))
