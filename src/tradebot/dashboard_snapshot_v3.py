"""M10 local-only dashboard projection. Never opens broker or provider clients."""
import json,time
from pathlib import Path
from tradebot.market_data_v3 import MARKETS
from tradebot.dashboard_analytics_v3 import analytics
from tradebot.opportunity_journal_v3 import ROUTE

SOURCES={
 "collector":("collector-status.json","as_of",150),
 "scanner":("scanner-status.json","checked_at",150),
 "position":("position-monitor-status.json","checked_at",150),
 "learning":("learning-status-v3.json","checked_at",660),
 "dispatch":("dispatch-readiness-v3.json","checked_at",150),
 "experience":("experience-status-v3.json","checked_at_us",900)
}
def source(root,name,now):
    filename,key,limit=SOURCES[name]
    p=root/filename
    try:
        if p.is_symlink(): raise ValueError()
        with p.open("rb") as f: raw=f.read(8_000_001)
        if len(raw)>8_000_000: raise ValueError()
        d=json.loads(raw); t=d[key]
        if type(t) not in (int,float): raise ValueError()
        if key.endswith("_us"): t=t/1e6
        age=now-t
        if not 0<=age: raise ValueError()
        if not isinstance(d["markets"],dict): raise ValueError()
        return {"state":"fresh" if age<=limit else "stale","age_seconds":int(age)},d
    except (OSError,ValueError,KeyError,TypeError):
        return {"state":"unavailable","age_seconds":None},{}

def select(obj,fields):
    return {k:obj.get(k) for k in fields}

def snapshot(root,*,now=None):
    root=Path(root); now=time.time() if now is None else now
    health={}; data={}
    for name in SOURCES: health[name],data[name]=source(root,name,now)
    result={"mode":"read_only_research_dashboard","checked_at":int(now),"sources":health,
            "markets":{},"execution_authorized":False}
    for s in MARKETS:
        a={n:d.get("markets",{}).get(s,{}) for n,d in data.items()}
        col=a["collector"]; scan=a["scanner"]; pos=a["position"].get("current",{}); learn=a["learning"]; exp=a["experience"]
        # Stale positions are never presented as current broker state.
        position=select(pos,("status","observed_at","open_order_count","halted","positions")) if health["position"]["state"]=="fresh" else {"status":"unknown"}
        j=data["scanner"].get("journal",{}).get(s,{})
        result["markets"][s]={
          "model_route":ROUTE[s],
          "feeds":{k:(v.get("status") if isinstance(v,dict) else v) for k,v in col.items()},
          "scanner":select(scan,("status","evaluations","signals","new_signals","candidate","deferred")),
          "journal":select(j,("events","signals")),
          "position":position,
          "learning":select(learn,("event_count","signal_horizon_rows","observed","pending","missing","rejected_events","trade_outcome_status")),
          "dispatch":select(a["dispatch"],("status","account_status","isolated_identity_verified","product_status","wire_prepared")),
          "experience":select(exp,("historical_evidence_status","synthetic_scorecard","historical_verified_subset")),
          "live_ai_enabled":False}
    result["analytics"]=analytics(root,now)
    return result
