"""Session context and historical public ticker changes; no trade actions."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from math import isfinite
from tradebot.market_data_v3 import normalize,FRAMES

SESSIONS={"tokyo":("Asia/Tokyo",9,18),"london":("Europe/London",8,17),
          "new_york":("America/New_York",8,17)}

def session_features(bars,*,as_of,frame="5m"):
    step=FRAMES[frame]
    now=datetime.fromtimestamp(as_of,timezone.utc)
    out={}
    for name,(zone,open_hour,close_hour) in SESSIONS.items():
        local=now.astimezone(ZoneInfo(zone))
        start=local.replace(hour=open_hour,minute=0,second=0,microsecond=0)
        end=local.replace(hour=close_hour,minute=0,second=0,microsecond=0)
        if local<start: start-=timedelta(days=1); end-=timedelta(days=1)
        a,b=int(start.timestamp()),int(end.timestamp())
        cutoff=min(as_of//step*step,b)
        out[name+"_active"]=int(a<=as_of<b)
        result={name+"_high":None,name+"_low":None,name+"_vwap":None}
        if a%step==0 and cutoff%step==0 and cutoff>a:
            rows=[r for r in bars if a<=r["time"]<cutoff]
            try: rows=normalize(rows,frame,as_of=cutoff,count=(cutoff-a)//step)
            except ValueError: rows=[]
            if rows:
                vol=sum(r["volume"] for r in rows)
                result.update({name+"_high":max(r["high"] for r in rows),
                    name+"_low":min(r["low"] for r in rows),
                    name+"_vwap":sum((r["high"]+r["low"]+r["close"])/3*r["volume"] for r in rows)/vol if vol else None})
        out.update(result)
    return out

def ticker_changes(samples,*,as_of):
    """Require a recent anchor and historical sample near each target."""
    now=as_of*1_000_000
    rows=sorted((r for r in samples if type(r.get("timestamp_us")) is int and 0<r["timestamp_us"]<=now),key=lambda x:x["timestamp_us"])
    latest=rows[-1] if rows and now-rows[-1]["timestamp_us"]<=120_000_000 else None
    out={}
    for minutes in (5,15,60):
        for key in ("oi_change_pct","funding_raw_change"):
            out[f"{key}_{minutes}m"]=None
        if latest is None: continue
        target=latest["timestamp_us"]-minutes*60_000_000
        old=next((r for r in reversed(rows) if r["timestamp_us"]<=target),None)
        if old is None or target-old["timestamp_us"]>90_000_000: continue
        for field,output,percent in (("open_interest_raw","oi_change_pct",True),("funding_rate_raw","funding_raw_change",False)):
            a,b=old.get(field),latest.get(field)
            if not all(isinstance(x,(int,float)) and not isinstance(x,bool) and isfinite(x) for x in (a,b)): continue
            if percent and (a<=0 or b<0): continue
            out[f"{output}_{minutes}m"]=100*(b/a-1) if percent else b-a
    return out
