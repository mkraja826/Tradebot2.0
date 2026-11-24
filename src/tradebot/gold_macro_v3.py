"""Daily macro confirmation, based on publication snapshots observed by the collector.
Not intraday DXY or yield data, and not historical point-in-time vintages.
"""
import csv,io
from datetime import date,datetime,timezone
from math import isfinite

KEYS={"broad_dollar":("DTWEXBGS",),"yields":("DGS10","DFII10")}

def history(raw,key,now):
    data={k:{} for k in KEYS[key]}
    for r in csv.DictReader(io.StringIO(raw)):
        d=date.fromisoformat(r["observation_date"])
        if d>=now.date(): continue
        for k,rows in data.items():
            try: v=float(r[k])
            except (ValueError,TypeError,KeyError): continue
            if not isfinite(v): continue
            if d in rows and rows[d]!=v: raise ValueError("conflicting_observation")
            rows[d]=v
    return {k:[{"date":d.isoformat(),"value":v} for d,v in sorted(rows.items())[-6:]] for k,rows in data.items()}

def features(refs,*,observed_at):
    out={"broad_dollar_5obs_pct":None,"nominal_yield_5obs_bp":None,"real_yield_5obs_bp":None}
    today=datetime.fromtimestamp(observed_at,timezone.utc).date()
    for key,keys in KEYS.items():
        try:
            item=refs[key]; stamp=item["observed_at"]
            if item["status"]!="ready" or type(stamp) not in (int,float) or not 0<=observed_at-stamp<=22200: continue
            hist=item["macro_history"]
            if hist["source"]!="fred_daily_as_observed": continue
            changes={}; dates={}
            for k in keys:
                rows=hist["series"][k]
                if not isinstance(rows,list) or len(rows)!=6: raise ValueError("missing_history")
                ds=[date.fromisoformat(r["date"]) for r in rows]
                vs=[r["value"] for r in rows]
                if ds!=sorted(set(ds)) or not 1<=(today-ds[-1]).days<=(8 if key=="broad_dollar" else 5) or (ds[-1]-ds[0]).days>12:
                    raise ValueError("stale_or_gapped_daily")
                if any(type(v) not in (int,float) or not isfinite(v) for v in vs): raise ValueError("invalid_value")
                dates[k]=ds
                if k=="DTWEXBGS":
                    if min(vs)<=0: raise ValueError("invalid_index")
                    changes["broad_dollar_5obs_pct"]=100*(vs[-1]/vs[0]-1)
                else: changes[("nominal" if k=="DGS10" else "real")+"_yield_5obs_bp"]=100*(vs[-1]-vs[0])
            if len(keys)==2 and dates[keys[0]]!=dates[keys[1]]: continue
            out.update(changes)
        except (ValueError,TypeError,KeyError,OverflowError): continue
    return out
