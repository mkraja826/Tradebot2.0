"""Delta BTC mark/index alignment and raw funding-distribution features."""
from math import isfinite
from statistics import mean,pstdev
from tradebot.delta import DEMO_API
from tradebot.market_intelligence_v3 import number

SERIES={"funding:1h":("FUNDING:BTCUSD","1h",3600,168),
        "mark:5m":("MARK:BTCUSD","5m",300,50),
        "index:5m":(".DEXBTUSD","5m",300,50)}

def normalize_series(raw,kind,*,as_of):
    _,_,step,count=SERIES[kind]; cutoff=as_of//step*step
    if not isinstance(raw,list) or len(raw)>count+2: raise ValueError("invalid_history")
    rows={}
    for r in raw:
        t=r["time"]
        if type(t) is not int or t%step or t<=0 or t>cutoff: raise ValueError("bad_timestamp")
        if t==cutoff: continue
        if t<cutoff-count*step: continue
        v=number(r["close"],positive=kind!="funding:1h")
        if t in rows: raise ValueError("duplicate_timestamp")
        rows[t]={"time":t,"close":v}
    return [rows[t] for t in sorted(rows)]

def collect(client,kind,*,as_of):
    if client.base_url!=DEMO_API or client.allow_orders is not False: raise ValueError("readonly_demo_required")
    name,res,step,count=SERIES[kind]; end=as_of//step*step
    raw=client._request("GET","/v2/history/candles",params={"symbol":name,"resolution":res,"start":end-count*step,"end":end})["result"]
    return normalize_series(raw,kind,as_of=as_of)

def tail(rows,step,count,as_of):
    end=as_of//step*step; a=rows[-count:]
    if len(a)!=count or [r["time"] for r in a]!=list(range(end-count*step,end,step)): return []
    return a

def features(funding,mark,index,*,as_of):
    out={"funding_prior_z":None,"funding_latest_z":None,"funding_variation_status":"missing_history",
         "basis_bps":None,"basis_prior_bps":None,"index_return_pct":None,"mark_return_pct":None}
    f=tail(funding,3600,74,as_of)
    if f:
        values=[number(r["close"]) for r in f]; baseline=values[:-2]; sd=pstdev(baseline)
        if sd>max(1e-12,abs(mean(baseline))*1e-9):
            avg=mean(baseline)
            out.update(funding_prior_z=(values[-2]-avg)/sd,funding_latest_z=(values[-1]-avg)/sd,funding_variation_status="ready")
        else: out["funding_variation_status"]="constant_baseline"
    m=tail(mark,300,2,as_of); i=tail(index,300,2,as_of)
    if m and i:
        a,b=[number(r["close"],positive=True) for r in m]; c,d=[number(r["close"],positive=True) for r in i]
        out.update(basis_prior_bps=10000*(a/c-1),basis_bps=10000*(b/d-1),
                   index_return_pct=100*(d/c-1),mark_return_pct=100*(b/a-1))
    return out
