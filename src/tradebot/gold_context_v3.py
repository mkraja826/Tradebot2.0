"""Gold-specific session anchors, using only completed bars before decision."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from tradebot.market_data_v3 import normalize,FRAMES
from tradebot.session_context_v3 import session_features
from tradebot.advanced_indicators_v3 import daily_pivots

def opening(as_of,zone,hour):
    local=datetime.fromtimestamp(as_of,timezone.utc).astimezone(ZoneInfo(zone))
    start=local.replace(hour=hour,minute=0,second=0,microsecond=0)
    if local<start: start-=timedelta(days=1)
    return int(start.timestamp())

def range_at(bars,start,end):
    if end<=start or start%300 or end%300: return None,None
    try:
        rows=normalize([x for x in bars if start<=x["time"]<end],"5m",as_of=end,count=(end-start)//300)
    except ValueError: return None,None
    return max(x["high"] for x in rows),min(x["low"] for x in rows)

def gold_context(bars,daily,*,closed_at,frame):
    step=FRAMES[frame]; t=closed_at-step
    tokyo=opening(t,"Asia/Tokyo",9)
    london=opening(t,"Europe/London",8)
    ny=opening(t,"America/New_York",8)
    # Opening windows are hypotheses, not exchange hours.
    x=session_features(bars,as_of=closed_at)
    for name,start in (("london",london),("new_york",ny)):
        x[name+"_opening"]=int(0<=t-start<3600)
    # Freeze the Asian and London reference ranges before the relevant open.
    asian_start=opening(london,"Asia/Tokyo",9)
    x["asian_pre_london_high"],x["asian_pre_london_low"]=range_at(bars,asian_start,min(london,asian_start+9*3600))
    london_start=opening(ny,"Europe/London",8)
    x["london_pre_ny_high"],x["london_pre_ny_low"]=range_at(bars,london_start,min(ny,london_start+9*3600))
    x["asian_prior_high"],x["asian_prior_low"]=range_at(bars,tokyo,min(t,tokyo+9*3600))
    x["overlap"]=int(bool(x["london_active"] and x["new_york_active"]))
    x["active_session_vwap"]=next((x[k+"_vwap"] for k in ("new_york","london","tokyo") if x[k+"_active"]),None)
    day=t//86400*86400
    try: prior=normalize([r for r in daily if r["time"]==day-86400],"1d",as_of=day,count=1)[0]
    except ValueError: prior=None
    vals=daily_pivots(prior) if prior else dict.fromkeys(("pivot","r1","s1","r2","s2"))
    vals.update({k:prior[k] if prior else None for k in ("high","low","close")})
    x.update({"previous_day_"+k:v for k,v in vals.items()})
    weekday=(day//86400+3)%7
    week=day-weekday*86400
    try: prev=normalize([r for r in daily if week-7*86400<=r["time"]<week],"1d",as_of=week,count=7)
    except ValueError: prev=[]
    x["previous_week_high"]=max(r["high"] for r in prev) if prev else None
    x["previous_week_low"]=min(r["low"] for r in prev) if prev else None
    return x
