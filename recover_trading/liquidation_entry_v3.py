"""V3 liquidation entry research; archived observations and candles only.

Shared event reservations compare entry policies without using later outcomes
to select the next opportunity. No order, broker, provider or journal writes.
"""
import argparse
import json
import math
import sqlite3
from bisect import bisect_left
from collections import Counter
from contextlib import closing
from pathlib import Path
from statistics import median

from .liquidation_ema9 import (
    SOURCE, burst_side, confirm, HOLD_MINUTES, ENTRY_SLIPPAGE_BPS, FEE_BPS,
)
from .tb2_backtest_tools import (
    COSTS, VARIANTS, check_window, indicators, load_bars, metrics, simulate, signatures,
)

VERSION = "liquidation-entry-research-v3"
POLICIES = ("breakout_v1", "intensity_breakout", "reversal_retest",
            "intensity_reversal_retest", "continuation_retest")
EXITS = {"fixed":("1m",None), "1m_V4":("1m",VARIANTS["V4"]),
         "3m_V2":("3m",VARIANTS["V2"])}
STEPS = {"1m":60,"3m":180}
LOOKBACK_MS = 2*3600*1000
SPACING_MS = 8*60*1000
MIN_PRIOR = 6
INTENSITY_RATIO = 2
CONFIRM_MINUTES = 10
# Fixed reservation includes the entire confirmation and holding period,
# including an incomplete observation minute. Independent of P&L.
RESERVATION_S = (CONFIRM_MINUTES + HOLD_MINUTES + 1)*60


def flow(stamp, payload, side):
    """Observed same-side size per minute, NOT total market liquidations."""
    if (payload.get("source") != SOURCE or payload.get("status") != "observed_research_only"):
        return None
    asof = payload.get("as_of_ms")
    if type(asof) is not int or not 0 <= stamp-asof <= 120000:
        return None
    try:
        f=payload["features"]
        size=float(f["observed_sizes_btc"][side])
        interval=float(f["interval_s"])
        if not math.isfinite(size) or not math.isfinite(interval) or size<=0 or not 300<=interval<=390:
            return None
        return size*60/interval
    except (KeyError,TypeError,ValueError,OverflowError):
        return None


def intensity(stamp,payload,side,prior):
    """Compare only earlier, spaced, positive observations. Unknown != zero."""
    current=flow(stamp,payload,side)
    ref=[]
    previous=stamp
    for t,p in reversed(prior):
        if t<stamp-LOOKBACK_MS:break
        if previous-t<SPACING_MS:continue
        v=flow(t,p,side)
        if v is None:continue
        ref.append(v);previous=t
    if current is None or len(ref)<MIN_PRIOR:
        return dict(status="insufficient_reference",reference_count=len(ref),ratio=None)
    ratio=current/median(ref)
    return dict(status="observed",reference_count=len(ref),ratio=ratio,
                qualifies=ratio>=INTENSITY_RATIO)


def retest(side,stamp,minute,kind):
    """Break, retest and close beyond a pre-observation 5m range.
    Reversal is a price-recovery proxy, not verified cessation of forced flow.
    """
    floor=stamp//60000*60
    first=(stamp+59999)//60000*60
    prev=[minute.get(t) for t in range(floor-300,floor,60)]
    if any(b is None for b in prev):return None,"missing_confirmation_path"
    high=max(b[1] for b in prev);low=min(b[2] for b in prev)
    cascade=-1 if side=="LONG" else 1
    sign=-cascade if kind=="reversal" else cascade
    level=high if sign==1 else low
    broken=False
    for t in range(first,first+CONFIRM_MINUTES*60,60):
        b=minute.get(t)
        if b is None:return None,"missing_confirmation_path"
        _,h,l,c,*_=b
        if not broken:
            if sign*(c-level)>0:broken=True
            continue
        if sign*(c-level)<0:
            broken=False
            continue
        if ((l<=level if sign==1 else h>=level) and sign*(c-level)>0):
            return (t+60,sign,kind),None
    return None,"no_confirmation"


def bracket(match,minute,maps,end):
    t,sign,_=match
    last=t+HOLD_MINUTES*60
    if last>end:return None,"incomplete_horizon"
    if any(i not in minute for i in range(t-300,last,60)):
        return None,"missing_minute_path"
    for frame,step in STEPS.items():
        if any(i//step*step not in maps[frame] for i in range(t,last,60)):
            return None,"missing_indicator_warmup"
    entry=minute[t][0]*(1+sign*ENTRY_SLIPPAGE_BPS/10000)
    atr=maps["1m"][t][2]
    recent=[minute[i] for i in range(t-300,t,60)]
    sl=min(b[2] for b in recent)-.25*atr if sign==1 else max(b[1] for b in recent)+.25*atr
    risk=sign*(entry-sl);tp=entry+sign*2*risk
    if not all(math.isfinite(x) and x>0 for x in (entry,sl,tp,risk,atr)):
        return None,"invalid_bracket"
    return dict(id=str(t),opened=t,closed=last,first=t,last=last,sign=sign,
                entry=entry,qty=1/entry,rate=FEE_BPS/20000,sl=sl,tp=tp,
                target_at_entry=tp,actual=None),None


def outcomes(policy,side,stamp,payload,prior,minute,maps,end,relative):
    if policy.startswith("intensity_"):
        if relative["status"]!="observed":
            return dict(status="unknown",reason="insufficient_intensity_reference")
        if not relative["qualifies"]:
            return dict(status="no_trade",reason="below_relative_intensity")
    if policy in ("breakout_v1","intensity_breakout"):
        floor=stamp//60000*60
        first=(stamp+59999)//60000*60
        # Check only required confirmation bars, not later bars after a confirmed entry.
        match=confirm(side,stamp,minute)
        reason=None if match else ("missing_confirmation_path" if
            floor-60 not in minute or any(t not in minute for t in range(first,first+300,60))
            else "no_confirmation")
    else:
        kind="continuation" if policy=="continuation_retest" else "reversal"
        match,reason=retest(side,stamp,minute,kind)
    if match is None:
        return dict(status="no_trade" if reason=="no_confirmation" else "unknown",reason=reason)
    t,reason=bracket(match,minute,maps,end)
    if t is None:return dict(status="unknown",reason=reason)
    sims={name:simulate(t,minute,maps[frame],STEPS[frame],variant,"original")
          for name,(frame,variant) in EXITS.items()}
    return dict(status="simulated_trade",kind=match[2],entry_at=match[0],
                direction="LONG" if match[1]==1 else "SHORT",entry=t["entry"],
                stop=t["sl"],target=t["tp"],exits=sims)


def summarize(events,policy):
    rows=[e["policies"][policy] for e in events]
    states=Counter(r["status"] for r in rows)
    trades=[r for r in rows if r["status"]=="simulated_trade"]
    result=dict(opportunities=len(rows),states=dict(states),
                reasons=dict(Counter(r.get("reason") for r in rows if r.get("reason"))),
                exits={})
    for name in EXITS:
        result["exits"][name]={}
        for c in map(str,COSTS):
            returns=[r["exits"][name]["net"][c]*10000 for r in trades]
            # Unknown rows never count as no trade or zero returns.
            known=states["simulated_trade"]+states["no_trade"]
            timeline=[r["exits"][name]["net"][c]*10000 if r["status"]=="simulated_trade" else 0
                      for r in rows if r["status"]!="unknown"]
            result["exits"][name][c]=dict(trade_metrics_bps=metrics(returns),
                known_opportunity_metrics_bps=metrics(timeline),
                complete_opportunity_coverage=known==len(rows))
    return result


def analyze(observations,minute,maps,start,split,end):
    if not start<split<end:raise ValueError("invalid split")
    history=sorted(observations,key=lambda x:x[0])
    stamps=[s for s,_ in history]
    if len(set(stamps))!=len(stamps):raise ValueError("duplicate observation timestamp")
    events=[];excluded=Counter();reserved=0
    for idx,(stamp,payload) in enumerate(history):
        if not start*1000<=stamp<end*1000:continue
        side=burst_side(stamp,payload)
        if side is None:
            excluded["not_qualifying_V1_burst"]+=1;continue
        if stamp<reserved:
            excluded["shared_reservation"]+=1;continue
        part="development" if stamp<split*1000 else "holdout"
        boundary=split if part=="development" else end
        reserved=stamp+RESERVATION_S*1000
        if reserved>boundary*1000:
            excluded["partition_boundary"]+=1;continue
        lo=bisect_left(stamps,stamp-LOOKBACK_MS,0,idx)
        prior=history[lo:idx]
        relative=intensity(stamp,payload,side,prior)
        result={p:outcomes(p,side,stamp,payload,prior,minute,maps,boundary,relative)
                for p in POLICIES}
        events.append(dict(observed_ms=stamp,partition=part,liquidated_side=side,
                           intensity=relative,policies=result))
    groups={}
    for part in ("development","holdout","all"):
        group=[e for e in events if part=="all" or e["partition"]==part]
        # Compare policies on a common fully observed subset as well as all available rows.
        common=[e for e in group if all(r["status"]!="unknown" for r in e["policies"].values())]
        groups[part]=dict(all_available={p:summarize(group,p) for p in POLICIES},
                          common_known_count=len(common),
                          common_known={p:summarize(common,p) for p in POLICIES})
    return dict(version=VERSION,execution_effect="none",status="observed" if events else "no_eligible_bursts",
                symbol="BTCUSD",start=start,split=split,end=end,opportunities=len(events),
                exclusions=dict(excluded),groups=groups,events=events,
                assumptions=dict(relative_intensity_ratio=INTENSITY_RATIO,prior_positive_samples=MIN_PRIOR,
                    lookback_minutes=120,minimum_spacing_minutes=8,reservation_seconds=RESERVATION_S,
                    fee_bps=FEE_BPS,entry_slippage_bps=ENTRY_SLIPPAGE_BPS,exit_slippage_bps=list(COSTS),
                    initial_stop="five completed minutes +/- 0.25 ATR",target="2R fixed research proxy"),
                limitations=[
                    "Same V1 qualifying burst universe, not a new liquidation detector; relative intensity is an additional filter.",
                    "Observed positive flow samples only, not complete market volume; no observed events is not known zero.",
                    "Reversal retest is price recovery proxy, not proof of liquidation exhaustion; no CVD or book absorption evidence.",
                    "Shared fixed reservation changes V1 cohort; breakout_v1 here is a matched opportunity control, not original eight-trade replay.",
                    "Equal unit notional, Delta trade-price OHLC proxy, Bybit BTCUSDT observations; no leverage, funding, AI costs or actual fills.",
                    "Missing confirmation/path/indicator data excluded from known opportunity returns, never counted as zero.",
                    "All inspected windows exploratory; no independently validated advantage or Gold source."
                ])


def run(root,journal,start,split,end):
    check_window(start,end)
    if not start<split<end:raise ValueError("invalid split")
    root=Path(root).resolve();journal=Path(journal).resolve()
    paths=[root/"market.sqlite",journal]
    before=signatures(paths)
    with closing(sqlite3.connect(journal.as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        history=[(s,json.loads(p)) for s,p in db.execute(
            "SELECT observed_ms,payload FROM observations WHERE observed_ms>=? AND observed_ms<? ORDER BY observed_ms",
            (max(0,start*1000-LOOKBACK_MS),end*1000))]
    maps={};bad={};minute={}
    for frame,step in STEPS.items():
        bars,bad[frame]=load_bars(root,"BTCUSD",frame,max(0,start//step*step-106*step),end)
        maps[frame]=indicators(bars,step)
        if frame=="1m":minute=bars
    result=analyze(history,minute,maps,start,split,end)
    if before!=signatures(paths):return dict(version=VERSION,execution_effect="none",status="snapshot_changed_retry")
    result.update(invalid_candles=bad,observation_count=sum(start*1000<=s<end*1000 for s,_ in history))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--market-root",required=True);p.add_argument("--hypotheses-db",required=True)
    for k in ("start","split","end"):p.add_argument("--"+k,required=True,type=int)
    a=p.parse_args()
    try:r=run(a.market_root,a.hypotheses_db,a.start,a.split,a.end)
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError) as e:
        r=dict(version=VERSION,execution_effect="none",status="research_data_unavailable_or_invalid",error_type=type(e).__name__)
    print(json.dumps(r,allow_nan=False))

if __name__=="__main__":main()
