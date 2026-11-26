"""Frozen prospective BTC liquidation study; read-only, no trade execution."""
import argparse
import hashlib
import json
import sqlite3
import time
from collections import Counter
from contextlib import closing
from pathlib import Path
from . import liquidation_entry_v3 as v3
from . import liquidation_progress_v4 as v4
from . import liquidation_structure_v5 as v5
from .liquidation_ema9 import burst_side, FEE_BPS
from .tb2_backtest_tools import COSTS, indicators, load_bars, metrics, signatures

VERSION="liquidation-prospective-v6"
# 2026-11-26 14:47 IST. No previously inspected window is eligible.
START=1795684620
END=START+30*86400
N=100
STEPS={"1m":60,"3m":180,"15m":900}
POLICIES=("breakout_fixed","retest_fixed","retest_1m_immediate","retest_3m_immediate",
          "retest_1m_oneR","retest_3m_oneR","retest_trend","retest_fee_room","retest_all_confluence")
PRIMARY="retest_fixed"

def state(row,exit_name):
    if row["status"]!="simulated_trade":
        return {k:row[k] for k in ("status","reason") if k in row}
    return dict(status="simulated_trade",net=row["exits"][exit_name]["net"])

def assess(stamp,side,payload,minute,maps,asof):
    control=v3.outcomes("breakout_v1",side,stamp,payload,[],minute,maps,asof,{})
    retest=v3.outcomes("continuation_retest",side,stamp,payload,[],minute,maps,asof,{})
    out={"breakout_fixed":state(control,"fixed"),"retest_fixed":state(retest,"fixed"),
         "retest_1m_immediate":state(retest,"1m_V4"),"retest_3m_immediate":state(retest,"3m_V2")}
    ctx=None
    if retest["status"]!="simulated_trade":
        for k in POLICIES[4:]:out[k]=state(retest,"fixed")
    else:
        at=retest["entry_at"];s=1 if retest["direction"]=="LONG" else -1
        e=retest["entry"];sl=retest["stop"];tp=retest["target"]
        t=dict(id=str(at),first=at,last=at+v3.HOLD_MINUTES*60,sign=s,entry=e,sl=sl,tp=tp,
               qty=1/e,rate=FEE_BPS/20000)
        for frame in ("1m","3m"):
            r=v4.progress(t,minute,maps,v4.POLICIES[frame+"_oneR"])
            out["retest_"+frame+"_oneR"]=dict(status="simulated_trade",net=r["net"])
        ctx=v5.context(at,s,minute,maps)
        for name,filters in (("retest_trend",("trend",)),("retest_fee_room",("fees",)),
                             ("retest_all_confluence",("trend","room","fees"))):
            status,reason=v5.classify(ctx,filters)
            out[name]=state(retest,"fixed") if status=="eligible" else dict(status=status,reason=reason)
    # Regime annotation is independent of subsequent prices; not an entry filter.
    floor=stamp//60000*60
    higher=maps["15m"].get(floor//900*900)
    bar=minute.get(floor-60)
    regime="unknown"
    if higher is not None and bar is not None and higher[2]>0 and bar[3]>0:
        e9,e21,atr=higher
        regime=("high_volatility" if atr/bar[3]*10000>=50 else
                "trending" if abs(e9-e21)>=.5*atr else "ranging")
    return dict(observed_ms=stamp,side=side,regime=regime,context=ctx,policies=out)

def summary(rows,name):
    outcomes=[r["policies"][name] for r in rows]
    states=Counter(r["status"] for r in outcomes)
    known=[r for r in outcomes if r["status"]!="unknown"]
    trades=[r for r in known if r["status"]=="simulated_trade"]
    costs={}
    for c in map(str,COSTS):
        costs[c]=dict(trade_metrics_bps=metrics([r["net"][c]*10000 for r in trades]),
            opportunity_metrics_bps=metrics([r["net"][c]*10000 if r["status"]=="simulated_trade" else 0 for r in known]))
    return dict(opportunities=len(rows),states=dict(states),costs=costs,
                complete_coverage=len(known)==len(rows))

def enroll(history,asof):
    """First N chronological nonoverlapping slots, independent of outcomes.
    Stop at the first immature slot. Never replace unknown or losing slots.
    """
    slots=[];reserved=START*1000
    for stamp,payload in sorted(history,key=lambda r:r[0]):
        if stamp<START*1000 or stamp>=END*1000 or stamp>=asof*1000:continue
        if stamp<reserved:continue
        side=burst_side(stamp,payload)
        if side is None:continue
        reserved=stamp+v3.RESERVATION_S*1000
        if reserved>asof*1000:break
        slots.append((stamp,side,payload))
        if len(slots)==N:break
    return slots

def analyze(history,minute,maps,asof):
    slots=enroll(history,asof)
    rows=[assess(stamp,side,payload,minute,maps,asof) for stamp,side,payload in slots]
    cohorts={"all":rows}
    for regime in ("trending","ranging","high_volatility","unknown"):
        cohorts[regime]=[r for r in rows if r["regime"]==regime]
    groups={}
    for k,r in cohorts.items():
        common=[e for e in r if all(x["status"]!="unknown" for x in e["policies"].values())]
        groups[k]=dict(all_available={p:summary(r,p) for p in POLICIES},
                       common_known_count=len(common),common_known={p:summary(common,p) for p in POLICIES})
    finished=asof>=END+v3.RESERVATION_S
    return dict(version=VERSION,execution_effect="none",symbol="BTCUSD",start=START,
                enrollment_end=END,as_of=asof,target=N,enrolled=len(rows),
                status="target_reached" if len(rows)==N else "window_ended" if finished else "collecting",
                primary=PRIMARY,reference="breakout_fixed",groups=groups,events=rows,
                cohort_sha256=hashlib.sha256(json.dumps([r["observed_ms"] for r in rows]).encode()).hexdigest(),
                limitations=["First 100 qualifying observed opportunities or 30-day enrollment end, whichever comes first.",
                "A fixed 71-minute reservation is research-only; excludes overlapping bursts regardless of outcomes.",
                "No-trade and unknown are separate; missing archive observations cannot be enumerated.",
                "Regime thresholds 50bps ATR and 0.5 ATR EMA separation are descriptive, frozen, not fitted.",
                "Only BTC reference-venue liquidation observations; no verified Gold liquidation source.",
                "No automatic candidate selection, no orders, no leverage/funding/AI costs. Data revisions may alter cohort; compare saved IDs, not only count."])

def run(root,journal,asof):
    if type(asof) is not int or not START<=asof<=int(time.time()):raise ValueError("invalid as_of")
    asof=min(asof,END+v3.RESERVATION_S)
    root=Path(root).resolve();journal=Path(journal).resolve()
    paths=[root/"market.sqlite",journal];before=signatures(paths)
    with closing(sqlite3.connect(journal.as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        history=[(s,json.loads(p)) for s,p in db.execute(
            "SELECT observed_ms,payload FROM observations WHERE observed_ms>=? AND observed_ms<? ORDER BY observed_ms",
            (START*1000,min(asof,END)*1000))]
    maps={};bad={}
    for f,step in STEPS.items():
        bars,bad[f]=load_bars(root,"BTCUSD",f,max(0,START//step*step-106*step),asof)
        maps[f]=indicators(bars,step)
        if f=="1m":minute=bars
    result=analyze(history,minute,maps,asof)
    if before!=signatures(paths):return dict(version=VERSION,execution_effect="none",status="snapshot_changed_retry")
    result.update(invalid_candles=bad,observation_count=len(history))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--market-root",required=True);p.add_argument("--hypotheses-db",required=True)
    p.add_argument("--as-of",type=int,default=int(time.time())//60*60)
    a=p.parse_args()
    try:r=run(a.market_root,a.hypotheses_db,a.as_of)
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError) as e:
        r=dict(version=VERSION,execution_effect="none",status="research_data_unavailable_or_invalid",error_type=type(e).__name__)
    print(json.dumps(r,allow_nan=False))

if __name__=="__main__":main()
