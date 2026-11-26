"""Frozen V3 continuation-retest exit research; no execution interfaces."""
import argparse
import json
import math
import sqlite3
from pathlib import Path

from .liquidation_ema9 import FEE_BPS, ENTRY_SLIPPAGE_BPS, HOLD_MINUTES
from .liquidation_ema9_multiframe import same_result
from .tb2_backtest_tools import COSTS, check_window, indicators, load_bars, metrics, simulate, signatures, VARIANTS

VERSION="liquidation-progress-stop-v4"
# frame, ATR buffer, activation R (None = fee coverage), BE-on-fee
POLICIES={"fee_BE":(None,0,None,True)}
for frame,buffer in (("1m",1),("3m",.25)):
    for suffix,r in (("fee",None),("halfR",.5),("oneR",1)):
        for be in (False,True):
            POLICIES[f"{frame}_{suffix}"+("_BE" if be else "")]=(frame,buffer,r,be)
STEPS={"1m":60,"3m":180}

def breakeven(t,slip_bps=2):
    """Trigger price whose modeled slipped exit exactly covers both fees."""
    s,e,r=t["sign"],t["entry"],t["rate"]
    return e*(1+s*r)/(1-s*r)/(1-s*slip_bps/10000)

def progress(t,minute,maps,policy):
    frame,buf,threshold,be=policy
    s,e,sl,tp,rate=(t[k] for k in ("sign","entry","sl","tp","rate"))
    risk=s*(e-sl);bep=breakeven(t)
    prev=None;active=False;fee_seen=False;adjustments=0;activation=None
    reason="time_cap";px=None;dual=False
    for i in range(t["first"],t["last"],60):
        o,h,l,c,*_=minute[i]
        if s*(o-sl)<=0:px=o;reason="stop_gap";break
        if s*(o-tp)>=0:px=tp;reason="target_gap";break
        # Only a completed post-entry candle can trigger a new stop.
        if prev is not None:
            if s*(prev-bep)>=0:fee_seen=True
            if frame and not active and (fee_seen if threshold is None else s*(prev-e)>=threshold*risk):
                active=True;activation=i
            candidate=sl
            if be and fee_seen:candidate=max(candidate,bep) if s==1 else min(candidate,bep)
            if active:
                step=STEPS[frame];ema,_,atr=maps[frame][i//step*step]
                value=ema-s*buf*atr
                candidate=max(candidate,value) if s==1 else min(candidate,value)
            if s*(candidate-sl)>0:sl=candidate;adjustments+=1
            if s*(o-sl)<=0:px=o;reason="progress_stop_crossed_at_update";break
        hit=l<=sl if s==1 else h>=sl
        target=h>=tp if s==1 else l<=tp
        if hit:px=sl;reason="stop";dual=target;break
        if target:px=tp;reason="target";break
        prev=c
    if px is None:i=t["last"]-60;px=minute[i][3]
    net={}
    for cost in COSTS:
        fill=px*(1-s*cost/10000)
        net[str(cost)]=(s*(fill-e)-rate*(e+fill))*t["qty"]
    return dict(id=t["id"],net=net,reason=reason,exit_bar=i,exit_price=px,
                final_sl=sl,adjustments=adjustments,activated=active,
                activation_bar=activation,fee_covered_close=fee_seen,dual_touch=dual)

def excursion(t,minute,result):
    s,e,sl=t["sign"],t["entry"],t["sl"];risk=s*(e-sl)
    def bounds(first,last):
        bars=[minute[i] for i in range(first,last,60)]
        if not bars:return None
        fav=max(s*((b[1] if s==1 else b[2])-e) for b in bars)
        adv=max(-s*((b[2] if s==1 else b[1])-e) for b in bars)
        return dict(favorable_R=round(max(0,fav)/risk,6),adverse_R=round(max(0,adv)/risk,6))
    return dict(full_reserved_horizon=bounds(t["first"],t["last"]),
                pre_exit_complete_bars=bounds(t["first"],result["exit_bar"]),
                post_exit_complete_bars=bounds(result["exit_bar"]+60,t["last"]))

def analyze(report,minute,maps):
    if report.get("version")!="liquidation-entry-research-v3" or report.get("symbol")!="BTCUSD" or report.get("status")!="observed":
        raise ValueError("V3 BTC report required")
    start,split,end=(report[k] for k in ("start","split","end"));check_window(start,end)
    if not start<split<end:raise ValueError("invalid split")
    if report["assumptions"]["fee_bps"]!=FEE_BPS or report["assumptions"]["entry_slippage_bps"]!=ENTRY_SLIPPAGE_BPS:
        raise ValueError("cost mismatch")
    results=[];mismatches=[];reserved=0
    for event in sorted(report["events"],key=lambda x:x["observed_ms"]):
        row=event["policies"]["continuation_retest"]
        if row["status"]!="simulated_trade":continue
        i=row["entry_at"];last=i+HOLD_MINUTES*60;part=event["partition"]
        s={"LONG":1,"SHORT":-1}[row["direction"]];e,sl,tp=(float(row[k]) for k in ("entry","stop","target"))
        if (type(i) is not int or i%60 or i<reserved or not start*1000<=event["observed_ms"]<i*1000
                or part!=("development" if event["observed_ms"]<split*1000 else "holdout")
                or last>(split if part=="development" else end) or row["kind"]!="continuation"
                or not all(math.isfinite(x) and x>0 for x in (e,sl,tp))
                or s*(e-sl)<=0 or s*(tp-e)<=0):raise ValueError("invalid frozen trade")
        reserved=last
        t=dict(id=str(i),opened=i,closed=last,first=i,last=last,sign=s,entry=e,qty=1/e,
               rate=FEE_BPS/20000,sl=sl,tp=tp,target_at_entry=tp,actual=None)
        if any(j not in minute for j in range(i,last,60)) or any(j//step*step not in maps[f] for f,step in STEPS.items() for j in range(i,last,60)):
            mismatches.append(dict(id=str(i),reason="missing_coverage"));continue
        if not math.isclose(minute[i][0]*(1+s*ENTRY_SLIPPAGE_BPS/10000),e,rel_tol=1e-9):
            mismatches.append(dict(id=str(i),reason="entry_changed"));continue
        controls={"fixed":simulate(t,minute,{},60,None,"original"),
                  "1m_V4":simulate(t,minute,maps["1m"],60,VARIANTS["V4"],"original"),
                  "3m_V2":simulate(t,minute,maps["3m"],180,VARIANTS["V2"],"original")}
        if not all(same_result(v,row["exits"][k]) for k,v in controls.items()):
            mismatches.append(dict(id=str(i),reason="V3_controls_changed"));continue
        trials={**controls,**{k:progress(t,minute,maps,p) for k,p in POLICIES.items()}}
        results.append(dict(id=str(i),partition=part,breakeven_trigger=breakeven(t),
                            exits=trials,excursions={k:excursion(t,minute,v) for k,v in trials.items()}))
    base=dict(version=VERSION,execution_effect="none",symbol="BTCUSD",start=start,split=split,end=end)
    if mismatches:return dict(**base,status="cohort_reproduction_failed",mismatches=mismatches)
    groups={}
    for part in ("development","holdout","all"):
        cohort=[r for r in results if part=="all" or r["partition"]==part]
        groups[part]={}
        for k in ("fixed","1m_V4","3m_V2",*POLICIES):
            groups[part][k]=dict(n=len(cohort),costs={})
            for c in map(str,COSTS):
                vals=[r["exits"][k]["net"][c]*10000 for r in cohort]
                diffs=[v-r["exits"]["fixed"]["net"][c]*10000 for v,r in zip(vals,cohort)]
                groups[part][k]["costs"][c]=dict(metrics_bps=metrics(vals),delta_bps=round(sum(diffs),6))
    return dict(**base,status="observed" if results else "no_eligible_entries",n=len(results),groups=groups,details=results,
                limitations=["Frozen V3 continuation-retest entries only; no new trades or independent holdout.",
                "Break-even uses 2 bps exit slippage and modeled fees; gaps and higher slippage can still lose.",
                "R thresholds use completed closes, not intrabar highs/lows. No stop widening. Stop-first on dual touch.",
                "Excursions after exit are hypothetical price paths, not executable returns; exit candle excluded from before/after bounds.",
                "Equal unit notional, no leverage, funding, AI costs or real fills."])

def run(root,report):
    root=Path(root).resolve();start,end=report["start"],report["end"];check_window(start,end)
    paths=[root/"market.sqlite"];before=signatures(paths);maps={};bad={}
    for f,step in STEPS.items():
        bars,bad[f]=load_bars(root,"BTCUSD",f,max(0,start//step*step-106*step),end)
        maps[f]=indicators(bars,step)
        if f=="1m":minute=bars
    out=analyze(report,minute,maps)
    if before!=signatures(paths):return dict(version=VERSION,execution_effect="none",status="snapshot_changed_retry")
    out["invalid_candles"]=bad
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--market-root",required=True);p.add_argument("--v3-report",required=True)
    a=p.parse_args()
    try:out=run(a.market_root,json.loads(Path(a.v3_report).read_text()))
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,ArithmeticError) as e:
        out=dict(version=VERSION,execution_effect="none",status="research_data_unavailable_or_invalid",error_type=type(e).__name__)
    print(json.dumps(out,allow_nan=False))

if __name__=="__main__":main()
