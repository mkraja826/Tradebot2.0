"""One-shot keyless network probe; no exchange authentication or orders."""
import json
import time
from tradebot.market_data_v3 import collect,public_client
from .gold_v2_engine import Bar,evaluate
from .gold_v2_public_feeds import PublicFeeds,feature_packet
from .gold_v2_fundamentals import collect_external,context
from .gold_v2_feed_diagnostics import probe_frame
from .chart_reference import ReferenceClient

def probe():
    now=int(time.time())
    client=public_client()
    raw=collect(client,"XAUTUSD",as_of=now,frames=("5m","15m","1h"),count=250)
    frames={};health={}
    for frame,sec in (("5m",300),("15m",900),("1h",3600)):
        item=raw["frames"][frame]
        health[frame]={"status":item["status"],"reason":item.get("reason"),"bars":len(item["bars"])}
        if item["status"]=="ready":
            frames[sec]=[Bar(b["time"]+sec,b["open"],b["high"],b["low"],b["close"],b["volume"]) for b in item["bars"]]
    report=evaluate(frames,now)
    comparison={frame:probe_frame(ReferenceClient(),frame,sec,now,frames[sec]) for frame,sec in (("5m",300),("15m",900),("1h",3600)) if sec in frames}
    feeds=PublicFeeds().collect()
    packet=feature_packet(feeds,time.time())
    public={k:{"collector_status":v.get("status"),"reason":v.get("reason"),
               "decision_status":packet["feeds"][k]["status"]} for k,v in feeds.items()}
    try:
        refs,spot=collect_external()
        macro=context(refs,spot,as_of=time.time())
        fundamental={"status":"observed_packet","bias":macro.get("macro_bias_hypothesis"),
                     "macro_available":{k:v is not None for k,v in macro.get("macro",{}).items()}}
    except Exception as exc:
        fundamental={"status":"unavailable","reason":type(exc).__name__}
    return {"version":"gold-v2-public-probe.2","execution_effect":"none","as_of":now,
            "candles":health,"reference_comparison":comparison,"engine_status":report.get("status"),"data_quality":report.get("data_quality"),
            "candidate_count":len(report.get("candidates",[])),"public":public,"fundamentals":fundamental}
if __name__=="__main__":
    print(json.dumps(probe(),indent=2,allow_nan=False),flush=True)
