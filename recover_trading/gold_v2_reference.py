"""Gold V2 production-reference research path, isolated from demo execution."""
import argparse
import json
import time
from statistics import median
from tradebot.market_data_v3 import normalize
from .chart_reference import ReferenceClient
from .gold_v2_engine import Bar,evaluate,ema
from .gold_v2_feed_diagnostics import anomalies

VERSION="gold-v2-reference.1"
SOURCE="delta_india_production_reference"
FRAMES=(("5m",300),("15m",900),("1h",3600))

def collect_reference(client,as_of,count=250):
    frames={};health={}
    for name,sec in FRAMES:
        end=as_of//sec*sec
        try:
            raw=client.candles(symbol="XAUTUSD",resolution=name,start=end-count*sec,end=end)
            rows=normalize(raw,name,as_of=as_of,count=count)
            frames[sec]=[Bar(b["time"]+sec,b["open"],b["high"],b["low"],b["close"],b["volume"]) for b in rows]
            health[name]={"status":"ready","bars":len(rows)}
        except Exception as exc:
            health[name]={"status":"unavailable","reason":type(exc).__name__,"bars":0}
    return frames,health

def close_diagnostics(bars):
    """Descriptive only; no claim that closes themselves are free of anomalies."""
    closes=[b.c for b in bars]
    if len(closes)<201:return None
    e=[ema(closes,n) for n in (9,21,50,200)]
    moves=[abs(b.c-a.c) for a,b in zip(bars,bars[1:])]
    return {"ema":e,"direction":1 if e[0]>e[1]>e[2]>e[3] else -1 if e[0]<e[1]<e[2]<e[3] else 0,
            "last_close":closes[-1],"median_absolute_close_change":median(moves[-40:]),
            "true_range_anomalies":len(anomalies(bars)),
            "semantics":"descriptive_close_only_not_entry_signal"}

def observe_reference(as_of,*,client=None):
    if type(as_of) is not int or as_of<=0:raise ValueError("invalid_cutoff")
    frames,health=collect_reference(ReferenceClient() if client is None else client,as_of)
    report=evaluate(frames,as_of)
    # Preserve all raw quality decisions and strictly prevent this report from
    # being consumed as an ordinary demo entry or validation record.
    report.update(signal_source=SOURCE,execution_eligible=False)
    return {"version":VERSION,"symbol":"XAUTUSD","status":"reference_research_only",
            "signal_source":SOURCE,"execution_eligible":False,"execution_effect":"none",
            "as_of":as_of,"feed_health":health,"strict_reference_report":report,
            "close_diagnostics":{str(s):close_diagnostics(b) for s,b in frames.items()},
            "demo_price_equivalence":"not_established"}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--once",action="store_true",required=True)
    p.parse_args()
    print(json.dumps(observe_reference(int(time.time())),indent=2,allow_nan=False))
if __name__=="__main__":main()
