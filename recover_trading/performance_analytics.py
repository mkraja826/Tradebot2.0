"""Read-only analytics of recent reconciled closed position episodes, not account equity."""
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from statistics import median
from .performance import dec,stamp
VERSION="performance-analytics-v1"

def utc(t):
    return t.astimezone(timezone.utc)

def scope(rows,expected,excursions,now):
    out={"status":"unavailable","expected_reconciled_episodes":expected,"basis":"recent_reconciled_closed_episodes_before_funding"}
    if type(expected) is not int or expected<0:return out
    data=[];seen=set()
    for e in rows:
        t=stamp({"created_at":e.get("closed")});start=stamp({"created_at":e.get("opened")})
        v=dec(e.get("net_before_funding"));key=(e.get("opened"),e.get("closed"),e.get("decision_id"))
        if t is None or start is None or t<=start or t.timestamp()>now+1 or v is None or key in seen or e.get("direction") not in ("LONG","SHORT"):return out
        seen.add(key);data.append((t,v,e,key))
    if len(data)>expected:return out
    data.sort(key=lambda x:x[0])
    out.update(status="observed" if data else "empty",episodes=len(data),truncated=len(data)<expected,
        start=utc(data[0][0]).isoformat() if data else None,end=utc(data[-1][0]).isoformat() if data else None)
    wins=[v for _,v,_,_ in data if v>0];losses=[-v for _,v,_,_ in data if v<0]
    positive=sum(wins,Decimal(0));negative=sum(losses,Decimal(0))
    out.update(wins=len(wins),losses=len(losses),breakeven=len(data)-len(wins)-len(losses),profit_factor=str(positive/negative) if negative else None,
        profit_factor_status="observed" if negative else "no_losing_episodes" if wins else "no_nonzero_episodes",
        average_win=str(positive/len(wins)) if wins else None,average_loss=str(-negative/len(losses)) if losses else None,
        average_net=str((positive-negative)/len(data)) if data else None,net=str(positive-negative) if data else None)
    days=defaultdict(lambda: [Decimal(0),0]);directions=defaultdict(list);buckets=defaultdict(Decimal)
    for t,v,e,_ in data:
        date=utc(t).date().isoformat();days[date][0]+=v;days[date][1]+=1
        directions[e["direction"]].append(v);buckets[t]+=v
    out["directions"]=[{"direction":k,"episodes":len(v),"net":str(sum(v,Decimal(0))) if v else None,"wins":sum(x>0 for x in v),"losses":sum(x<0 for x in v)} for k,v in ((k,directions[k]) for k in ("LONG","SHORT"))]
    total=peak=max_dd=Decimal(0);curve=[]
    for t,v in sorted(buckets.items()):
        total+=v;peak=max(peak,total);dd=peak-total;max_dd=max(max_dd,dd)
        curve.append({"closed":utc(t).isoformat(),"cumulative_net":str(total),"drawdown":str(dd)})
    out.update(curve=curve,max_closed_pnl_drawdown=str(max_dd) if data else None)
    today=datetime.fromtimestamp(now,timezone.utc).date()
    out["calendar"]=[{"date":day.isoformat(),"net":str(days[day.isoformat()][0]) if day.isoformat() in days else None,"episodes":days[day.isoformat()][1] if day.isoformat() in days else 0} for day in (today-timedelta(days=i) for i in range(29,-1,-1))]
    matched=defaultdict(list)
    for x in excursions:
        if isinstance(x,dict):matched[(x.get("opened"),x.get("closed"),x.get("decision_id"))].append(x)
    retention=[]
    for _,v,e,k in data:
        group=matched.get(k,[])
        if len(group)!=1:continue
        x=group[0];mfe=dec(x.get("mfe_bps"));gross=dec(x.get("gross_weighted_exit_return_bps"));ratio=dec(x.get("observed_capture_upper_bound_pct"))
        if x.get("status")!="complete_interior_lower_bound" or x.get("coverage")!=1 or x.get("direction")!=e["direction"] or dec(x.get("realized_net_before_funding"))!=v or mfe is None or gross is None or ratio is None or not 0<gross<=mfe or not 0<ratio<=100:continue
        retention.append({"closed":e["closed"],"direction":e["direction"],"mfe_bps":float(mfe),"gross_exit_bps":float(gross),"capture_upper_bound_pct":float(ratio)})
    out["retention"]={"eligible_episodes":len(retention),"median_capture_upper_bound_pct":median(r["capture_upper_bound_pct"] for r in retention) if retention else None,"rows":retention}
    return out

def build(performance,excursions,now):
    out={"version":VERSION,"currency":performance.get("currency"),"execution_effect":"none","status":"unavailable"}
    if performance.get("status")!="reconciled_subset" or not out["currency"]:return out
    rows=performance.get("recent_episodes") or []
    ex=(excursions or {}).get("episodes") or []
    out.update(status="observed",recover=scope([e for e in rows if e.get("attribution")=="single_recover_entry_order" and e.get("decision_id")],(performance.get("recover_attributed") or {}).get("closed_episodes"),ex,now),
        account=scope(rows,(performance.get("all_reconciled") or {}).get("closed_episodes"),ex,now))
    return out
