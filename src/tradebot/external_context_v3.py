"""Public external reference context. Gold token and USD index are proxies."""
import csv,io,json
from datetime import datetime,timezone,timedelta
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo
from math import isfinite

URLS={
 "btc_spot":"https://api.exchange.coinbase.com/products/BTC-USD/ticker",
 "gold_token_proxy":"https://api.exchange.coinbase.com/products/PAXG-USD/ticker",
 "yields":"https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10,DFII10",
 "broad_dollar":"https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS",
 "bls_calendar":"https://www.bls.gov/schedule/news_release/bls.ics"}
from tradebot.news_context_v3 import URLS as NEWS_URLS
URLS.update(NEWS_URLS)
from tradebot.gold_stress_v3 import URLS as STRESS_URLS
URLS.update(STRESS_URLS)
def fetch(key):
    with urlopen(Request(URLS[key],headers={"User-Agent":"Tradebot research/3.0"}),timeout=8) as r:
        raw=r.read(2_000_001)
    if len(raw)>2_000_000: raise ValueError("oversize_feed")
    return raw.decode("utf-8")
def spot(raw,now):
    x=json.loads(raw)
    stamp=datetime.fromisoformat(x["time"].replace("Z","+00:00"))
    age=(now-stamp).total_seconds()
    p,b,a=(float(x[k]) for k in ("price","bid","ask"))
    if not 0<=age<=120 or not all(map(isfinite,(p,b,a))) or not 0<b<a or p<=0:
        raise ValueError("invalid_or_stale_reference")
    return {"trade_at":stamp.isoformat(),"price":p,"bid":b,"ask":a}
def daily(raw,keys,now):
    out={}
    for row in csv.DictReader(io.StringIO(raw)):
        date=datetime.fromisoformat(row["observation_date"]).date()
        if date>now.date(): continue
        for key in keys:
            try: value=float(row[key])
            except (ValueError,TypeError): continue
            if isfinite(value) and (key not in out or date.isoformat()>out[key]["date"]):
                out[key]={"date":date.isoformat(),"value":value}
    if set(out)!=set(keys): raise ValueError("missing_series")
    for item in out.values():
        item["age_days"]=(now.date()-datetime.fromisoformat(item["date"]).date()).days
        if item["age_days"]>10: raise ValueError("stale_daily_series")
    return out
def calendar(raw,now):
    raw=raw.replace("\r\n","\n")
    if "BEGIN:VCALENDAR" not in raw or "END:VCALENDAR" not in raw: raise ValueError("invalid_calendar")
    events=[]
    for event in raw.split("BEGIN:VEVENT")[1:]:
        lines=event.split("END:VEVENT",1)[0].splitlines()
        title=next((s[8:] for s in lines if s.startswith("SUMMARY:")),"")
        if not any(k in title.lower() for k in ("consumer price index","employment situation","producer price index")): continue
        if "STATUS:CANCELLED" in lines: continue
        start=next((s for s in lines if s.startswith("DTSTART;TZID=US-Eastern:")),None)
        if not start: continue
        t=datetime.strptime(start.split(":",1)[1],"%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
        if now<=t<=now+timedelta(days=45): events.append({"title":title,"utc":t.isoformat()})
    return sorted(events,key=lambda e:e["utc"])
