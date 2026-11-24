"""Daily VIX / weekly financial stress, not real-time market panic evidence."""
import csv,io
from datetime import date,datetime,timezone
from math import isfinite
URLS={"market_vix":"https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS",
      "financial_stress":"https://fred.stlouisfed.org/graph/fredgraph.csv?id=STLFSI4"}
FIELDS={"market_vix":("VIXCLS",6,5,12),"financial_stress":("STLFSI4",2,17,7)}

def parse(raw,key,now):
    field,n,maxage,span=FIELDS[key]
    rows={}
    for r in csv.DictReader(io.StringIO(raw)):
        d=date.fromisoformat(r["observation_date"])
        if d>=now.date(): continue
        try: v=float(r[field])
        except (ValueError,TypeError): continue
        if not isfinite(v) or (key=="market_vix" and v<=0): continue
        if d in rows and rows[d]!=v: raise ValueError("conflicting_observation")
        rows[d]=v
    selected=sorted(rows.items())[-n:]
    out={"source":"fred_as_observed","series":field,"observations":[{"date":d.isoformat(),"value":v} for d,v in selected]}
    validate(out,key,now.date())
    return out

def validate(data,key,today):
    field,n,maxage,span=FIELDS[key]
    if data["source"]!="fred_as_observed" or data["series"]!=field: raise ValueError("wrong_series")
    rows=data["observations"]
    if len(rows)!=n: raise ValueError("missing_history")
    ds=[date.fromisoformat(r["date"]) for r in rows]; vs=[r["value"] for r in rows]
    if ds!=sorted(set(ds)) or not 1<=(today-ds[-1]).days<=maxage or (ds[-1]-ds[0]).days>span: raise ValueError("stale_or_gapped")
    if key=="financial_stress" and (ds[-1]-ds[0]).days!=7: raise ValueError("missing_week")
    if any(type(v) not in (float,int) or not isfinite(v) or (key=="market_vix" and v<=0) for v in vs): raise ValueError("bad_value")
    return vs

def features(refs,*,observed_at):
    today=datetime.fromtimestamp(observed_at,timezone.utc).date()
    out={"vix_daily":None,"vix_5obs_change":None,"stress_weekly":None,"stress_weekly_change":None}
    for key in FIELDS:
        try:
            item=refs[key]
            if item["status"]!="ready" or type(item["observed_at"]) not in (float,int) or not 0<=observed_at-item["observed_at"]<=22200: continue
            vs=validate(item["data"],key,today)
            if key=="market_vix": out.update(vix_daily=vs[-1],vix_5obs_change=vs[-1]-vs[0])
            else: out.update(stress_weekly=vs[-1],stress_weekly_change=vs[-1]-vs[0])
        except (ValueError,TypeError,KeyError,OverflowError): continue
    return out
