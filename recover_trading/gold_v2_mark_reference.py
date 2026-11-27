"""Independent mark-price candle research, no volume or fill inference."""
from tradebot.market_data_v3 import normalize
from .gold_v2_engine import Bar,evaluate
from .gold_v2_reference import FRAMES
from .gold_v2_feed_diagnostics import anomalies
from .chart_reference import ReferenceClient
from tradebot.market_data_v3 import public_client
import time,json

VERSION="gold-v2-mark-reference.1"
SYMBOL="MARK:XAUTUSD"

def collect_mark(reader,as_of,count=250):
    frames={};health={}
    for name,sec in FRAMES:
        end=as_of//sec*sec
        try:
            rows=reader(dict(symbol=SYMBOL,resolution=name,start=end-count*sec,end=end))
            if not isinstance(rows,list):raise ValueError("invalid_response")
            # Mark prices do not have traded volume. Use zero as an explicit
            # non-volume sentinel for the existing Bar type; never impute OHLC.
            clean=normalize([dict(r,volume=0) for r in rows],name,as_of=as_of,count=count)
            frames[sec]=[Bar(r["time"]+sec,r["open"],r["high"],r["low"],r["close"],0) for r in clean]
            health[name]={"status":"ready","bars":len(clean),"true_range_anomalies":len(anomalies(frames[sec]))}
        except Exception as exc:
            health[name]={"status":"unavailable","reason":type(exc).__name__,"bars":0}
    return frames,health

def research(reader,as_of,*,source):
    if source not in ("production_mark","demo_mark"):raise ValueError("invalid_source")
    frames,health=collect_mark(reader,as_of)
    report=evaluate(frames,as_of)
    # Remove volume-dependent families even if the engine changes later.
    report["candidates"]=[c for c in report["candidates"] if c["family"] not in
        ("volume_confirmed_breakout","vwap_trend_reclaim","range_rsi_reversal")]
    report.update(signal_source=source,execution_eligible=False,
        volume_semantics="unavailable_for_mark_prices",execution_effect="none")
    return {"version":VERSION,"symbol":"XAUTUSD","source":source,"status":report["status"],
            "data_quality":report["data_quality"],"feed_health":health,
            "candidate_count":len(report["candidates"]),"report":report,"execution_effect":"none"}

def probe():
    now=int(time.time());r=ReferenceClient();d=public_client()
    p=research(lambda params:r.get("/v2/history/candles",params),now,source="production_mark")
    q=research(lambda params:d._request("GET","/v2/history/candles",params=params)["result"],now,source="demo_mark")
    from .gold_v2_mark_aggregation import probe as audit_aggregation
    out={k:{a:b for a,b in v.items() if a!="report"} for k,v in (("production",p),("demo",q))}
    out["aggregation_audit"]={
        "production":audit_aggregation(lambda params:r.get("/v2/history/candles",params),now),
        "demo":audit_aggregation(lambda params:d._request("GET","/v2/history/candles",params=params)["result"],now)}
    from .gold_v2_mark_model import evaluate_mark
    from .gold_v2_mark_aggregation import collect as collect_exact
    try:
        primary,_=collect_mark(lambda params:r.get("/v2/history/candles",params),now)
        peer,_=collect_mark(lambda params:d._request("GET","/v2/history/candles",params=params)["result"],now)
        fine=collect_exact(lambda params:r.get("/v2/history/candles",params),"5m",300,now//900*900,750)
        model=evaluate_mark(primary,peer,fine,now)
        out["corroborated_model"]={k:model[k] for k in ("status","data_quality","candidates","execution_eligible")}
    except Exception as exc:
        out["corroborated_model"]={"status":"unavailable","reason":type(exc).__name__,"execution_eligible":False}
    return out
if __name__=="__main__":print(json.dumps(probe(),indent=2,allow_nan=False))
