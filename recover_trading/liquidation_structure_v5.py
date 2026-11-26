"""V5 liquidation confluence research. Read-only, no execution dependencies."""
import argparse
import json
import math
import sqlite3
from pathlib import Path
from contextlib import closing

from . import liquidation_entry_v3 as v3
from .tb2_backtest_tools import COSTS, check_window, indicators, load_bars, metrics, signatures

VERSION="liquidation-structure-confluence-v5"
POLICIES={"retest_control":(), "trend_aligned":("trend",),
          "structure_room":("room",), "fee_room":("fees",),
          "all_confluence":("trend","room","fees")}
STEPS={"1m":60,"3m":180,"15m":900}
LOOKBACK=60
# Fixed illustrative research assumptions, not optimized.
COST_BPS=v3.FEE_BPS+v3.ENTRY_SLIPPAGE_BPS+5
MIN_REWARD_COST=2

def context(t,sign,minute,maps):
    """All inputs are available by the confirmation close, before entry open."""
    out={"trend":None,"room":None,"fees":None}
    rows=[minute.get(i) for i in range(t-LOOKBACK*60,t,60)]
    last=minute.get(t-60)
    a=maps["1m"].get(t)
    higher=maps["15m"].get(t//900*900)
    if higher is not None and last is not None:
        e9,e21,_=higher
        out["trend"]=sign*(e9-e21)>0 and sign*(last[3]-e21)>0
        out["ema15_9"]=e9;out["ema15_21"]=e21
    if a is None or last is None or any(b is None for b in rows):return out
    # Entry is estimated from the known close, never from next open.
    e=last[3]*(1+sign*v3.ENTRY_SLIPPAGE_BPS/10000)
    recent=rows[-5:]
    stop=min(b[2] for b in recent)-.25*a[2] if sign==1 else max(b[1] for b in recent)+.25*a[2]
    risk=sign*(e-stop)
    if not all(math.isfinite(x) and x>0 for x in (e,stop,risk)):return out
    target=e+sign*2*risk
    if target<=0:return out
    out.update(estimated_entry=e,estimated_stop=stop,estimated_target=target,
               target_distance_bps=2*risk/e*10000)
    out["fees"]=out["target_distance_bps"]>=MIN_REWARD_COST*COST_BPS
    # Confirmed pivot (two neighbors on each side), strictly beyond planned entry.
    k=1 if sign==1 else 2
    levels=[]
    for j in range(2,len(rows)-2):
        level=rows[j][k]
        if all(sign*(level-rows[n][k])>0 for n in (j-2,j-1,j+1,j+2)) and sign*(level-e)>0:
            levels.append(level)
    if levels:
        level=min(levels) if sign==1 else max(levels)
        out["nearest_obstacle"]=level
        out["room_R"]=sign*(level-e)/risk
        out["room"]=out["room_R"]>=2
    # No observed pivot is unknown, not unlimited room.
    return out

def classify(ctx,filters):
    if any(ctx[k] is False for k in filters):return "no_trade","confluence_not_met"
    if any(ctx[k] is None for k in filters):return "unknown","missing_confluence_evidence"
    return "eligible",None

def summarize(events,policy):
    known=[e["policies"][policy] for e in events if e["policies"][policy]["status"]!="unknown"]
    trades=[e for e in known if e["status"]=="simulated_trade"]
    result={"opportunities":len(events),"trades":len(trades),"unknown":len(events)-len(known),
            "no_trade":len(known)-len(trades),"costs":{}}
    for c in map(str,COSTS):
        vals=[r["fixed"]["net"][c]*10000 for r in trades]
        timeline=[r["fixed"]["net"][c]*10000 if r["status"]=="simulated_trade" else 0 for r in known]
        result["costs"][c]={"trade_metrics_bps":metrics(vals),"known_opportunity_metrics_bps":metrics(timeline)}
    return result

def analyze(history,minute,maps,start,split,end):
    base=v3.analyze(history,minute,maps,start,split,end)
    events=[]
    for event in base["events"]:
        row=event["policies"]["continuation_retest"]
        ctx=None
        if row["status"]=="simulated_trade":
            ctx=context(row["entry_at"],1 if row["direction"]=="LONG" else -1,minute,maps)
        policies={}
        for name,filters in POLICIES.items():
            if row["status"]!="simulated_trade":
                policies[name]={k:row[k] for k in ("status","reason") if k in row};continue
            state,reason=classify(ctx,filters)
            policies[name]=dict(status="simulated_trade",fixed=row["exits"]["fixed"]) if state=="eligible" else dict(status=state,reason=reason)
        events.append(dict(observed_ms=event["observed_ms"],partition=event["partition"],
                           entry_at=row.get("entry_at"),direction=row.get("direction"),
                           context=ctx,policies=policies))
    groups={}
    for part in ("development","holdout","all"):
        cohort=[e for e in events if part=="all" or e["partition"]==part]
        common=[e for e in cohort if all(r["status"]!="unknown" for r in e["policies"].values())]
        groups[part]=dict(all_available={p:summarize(cohort,p) for p in POLICIES},
                          common_known_count=len(common),common_known={p:summarize(common,p) for p in POLICIES})
    return dict(version=VERSION,execution_effect="none",symbol="BTCUSD",status=base["status"],
                start=start,split=split,end=end,opportunities=len(events),exclusions=base["exclusions"],
                groups=groups,events=events,assumptions=dict(structure_lookback_minutes=LOOKBACK,
                    pivot_neighbors=2,minimum_room_R=2,min_reward_cost_multiple=MIN_REWARD_COST,
                    assumed_cost_bps=COST_BPS,trend="completed 15m EMA9/21 alignment and confirmation close vs EMA21",
                    bracket="V3 fixed structural stop, 2R target, 60m horizon"),
                limitations=["Same V3 continuation retest and reservation; no entry timing optimization.",
                    "Context uses estimated entry from confirmation close; actual next open may gap.",
                    "Missing pivots or indicators are unknown, not a passing signal.",
                    "Pivot levels are historical price proxies, not observed liquidity or guaranteed support/resistance.",
                    "All filters exploratory; use genuinely later data for validation. No leverage, funding or actual execution."])

def run(root,journal,start,split,end):
    check_window(start,end)
    if not start<split<end:raise ValueError("invalid split")
    root=Path(root).resolve();journal=Path(journal).resolve()
    paths=[root/"market.sqlite",journal];before=signatures(paths)
    with closing(sqlite3.connect(journal.as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        history=[(s,json.loads(p)) for s,p in db.execute(
            "SELECT observed_ms,payload FROM observations WHERE observed_ms>=? AND observed_ms<? ORDER BY observed_ms",
            (max(0,start*1000-v3.LOOKBACK_MS),end*1000))]
    maps={};bad={}
    for f,step in STEPS.items():
        bars,bad[f]=load_bars(root,"BTCUSD",f,max(0,start//step*step-106*step),end)
        maps[f]=indicators(bars,step)
        if f=="1m":minute=bars
    result=analyze(history,minute,maps,start,split,end)
    if before!=signatures(paths):return dict(version=VERSION,execution_effect="none",status="snapshot_changed_retry")
    result["invalid_candles"]=bad
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--market-root",required=True);p.add_argument("--hypotheses-db",required=True)
    for k in ("start","split","end"):p.add_argument("--"+k,required=True,type=int)
    a=p.parse_args()
    try:r=run(a.market_root,a.hypotheses_db,a.start,a.split,a.end)
    except (OSError,sqlite3.Error,ValueError,KeyError,TypeError,ArithmeticError) as e:
        r=dict(version=VERSION,execution_effect="none",status="research_data_unavailable_or_invalid",error_type=type(e).__name__)
    print(json.dumps(r,allow_nan=False))

if __name__=="__main__":main()
