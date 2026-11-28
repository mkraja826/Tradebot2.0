"""Gold V2 only: official Fed H.10/H.15 publication fallback."""
import csv,io,time
from datetime import date,datetime,timezone
from math import isfinite
from urllib.parse import urlencode
from .macro_feed import fetch

BASE="https://www.federalreserve.gov/datadownload/Output.aspx?"
SERIES={
    "broad_dollar":("H10","122e3bcb627e8e53f1bf72a1a09cfb81","JRXWTFB_N.B",8),
    "real_yield":("H15","0b98a66d3ff5e1ea0fbf88adc59b387f","RIFLGFCY10_XII_N.B",5),
}
def url(key):
    rel,package,_,_=SERIES[key]
    return BASE+urlencode(dict(filetype="csv",label="include",lastobs=10,layout="seriescolumn",rel=rel,series=package,type="package"))
def parse(raw,key,now):
    rel,_,ident,max_age=SERIES[key]
    today=datetime.fromtimestamp(now,timezone.utc).date()
    rows=list(csv.reader(io.StringIO(raw)))
    headers=[(i,r) for i,r in enumerate(rows) if r and r[0]=="Time Period"]
    if len(headers)!=1:raise ValueError("missing_header")
    i,header=headers[0]
    if header.count(ident)!=1:raise ValueError("wrong_series")
    col=header.index(ident)
    # Check the full published identifier, not just the human-readable label.
    ids=[r for r in rows[:i] if r and r[0]=="Unique Identifier"]
    if len(ids)!=1 or len(ids[0])<=col or ids[0][col]!=rel+"/"+rel+"/"+ident:raise ValueError("wrong_identifier")
    values={}
    for row in rows[i+1:]:
        if not row:continue
        if len(row)!=len(header):raise ValueError("malformed_row")
        d=date.fromisoformat(row[0])
        if d>=today:continue
        if row[col] in ("","ND","."):continue
        v=float(row[col])
        if not isfinite(v) or key=="broad_dollar" and v<=0:raise ValueError("invalid_value")
        if d in values and values[d]!=v:raise ValueError("conflicting_date")
        values[d]=v
    days=sorted(values)[-6:]
    if len(days)!=6 or not 1<=(today-days[-1]).days<=max_age or (days[-1]-days[0]).days>12:
        raise ValueError("stale_or_gapped_daily")
    return {"source":"federal_reserve_board_"+rel.lower()+"_as_observed","status":"ready","observed_at":now,
            "series":ident,"observations":[{"date":d.isoformat(),"value":values[d]} for d in days],
            "change":100*(values[days[-1]]/values[days[0]]-1) if key=="broad_dollar" else 100*(values[days[-1]]-values[days[0]])}
def collect(*,reader=fetch,clock=time.time):
    from concurrent.futures import ThreadPoolExecutor
    def one(k):
        try:return k,parse(reader(url(k)),k,clock())
        except Exception as exc:return k,{"status":"unavailable","reason":type(exc).__name__}
    with ThreadPoolExecutor(max_workers=2) as pool:return dict(pool.map(one,SERIES))
def apply_fallback(macro,refs,now):
    result=dict(macro);sources={}
    for key,field in (("broad_dollar","broad_dollar_5obs_pct"),("real_yield","real_yield_5obs_bp")):
        if result.get(field) is not None:continue
        item=refs.get("fed_official",{}).get(key,{})
        if item.get("status")!="ready":continue
        try:
            if not 0<=now-item["observed_at"]<=22200:continue
            # Revalidate publication age at projection, retaining true provider provenance.
            days=[date.fromisoformat(r["date"]) for r in item["observations"]]
            today=datetime.fromtimestamp(now,timezone.utc).date()
            if len(days)!=6 or not 1<=(today-days[-1]).days<=SERIES[key][3]:continue
            result[field]=item["change"]
            sources[key]={"source":item["source"],"observed_at":item["observed_at"],"series":item["series"],"last_date":days[-1].isoformat()}
        except (KeyError,TypeError,ValueError):continue
    return result,sources
