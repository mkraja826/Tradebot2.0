"""Bounded read-only replay tools for the separately hosted Tb2.0 MCP.
No broker, AI, shell, arbitrary paths, writes or execution policy changes.
"""
import json
import math
import sqlite3
import time
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal

from . import trade_intelligence

VERSION = "tb2-backtest-v1"
Market = Literal["BTCUSD", "XAUTUSD"]
Frame = Literal["1m", "3m", "5m", "15m", "30m", "1h"]
Target = Literal["original", "fixed_ema21", "dynamic_ema21"]
FRAMES = {"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"1h":3600}
MARKETS = ("BTCUSD","XAUTUSD")
VARIANTS = {"baseline":None, **{"V"+str(i+1):(b,False) for i,b in enumerate((0,.25,.5,1))},
            **{"V"+str(i+5):(b,True) for i,b in enumerate((0,.25,.5,1))}}
COSTS = (0,2,5)
MAX_WINDOW = 31*86400
LIMITATIONS = [
    "Retrospective exit-only replay of reconciled single-opening-fill episodes. Full original quantity until simulated exit; no historical partial reductions or re-entry.",
    "Original close time caps the simulation; not an independently executable portfolio backtest. Partial boundary bars excluded; intrabar path unknown.",
    "Trade-price 1m OHLC proxy, not mark trigger or executable quote history. Stop-first on dual touch; adverse open gaps modeled; no depth, latency or liquidation model.",
    "Historical blended fee rate inferred from entry and gross P&L. Additional adverse exit slippage scenarios 0/2/5 bps; funding and AI costs excluded.",
    "EMA9/EMA21 and Wilder ATR14 use confirmed contiguous bars, at least 105 warmup bars. Archive revisions and snapshot coverage may affect results.",
    "Compare candidates only on identical eligible episodes within a frame. Different frames can have different coverage. No holdout, no validated edge or deployment recommendation.",
    "Delayed activation requires a completed post-entry minute whose hypothetical exit covers inferred fees and 2bp slippage. Updates at the next minute open."
]

def epoch(s):
    return datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()

def check_window(start,end):
    if type(start) is not int or type(end) is not int or not 0<=start<end<=int(time.time()) or end-start>MAX_WINDOW:
        raise ValueError("use UTC epoch seconds, historical window up to 31 days")

def integer(value,lo,hi):
    if type(value) is not int or not lo<=value<=hi:
        raise ValueError("integer outside permitted bounds")
    return value

def finite(value):
    x=float(value)
    if not math.isfinite(x):raise ValueError("nonfinite number")
    return x

def response(**kw):
    return {"version":VERSION,"execution_effect":"none",**kw}

def load_bars(root,symbol,frame,start,end):
    step=FRAMES[frame];out={};bad=0
    with closing(sqlite3.connect((root/"market.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        rows=db.execute("SELECT stamp,payload FROM samples WHERE symbol=? AND series=? AND stamp>=? AND stamp<? ORDER BY stamp",
                        (symbol,"candle:"+frame,start,end))
        for t,p in rows:
            try:
                r=json.loads(p);o,h,l,c=(finite(r[k]) for k in ("open","high","low","close"))
                if type(t) is not int or t%step or r["time"]!=t or not 0<l<=min(o,c)<=max(o,c)<=h:
                    raise ValueError("invalid candle")
                if t+step>end:continue
                if t in out:raise ValueError("duplicate candle")
                volume=finite(r["volume"]) if r.get("volume") is not None else None
                if volume is not None and volume<0:raise ValueError("negative volume")
                out[t]=(o,h,l,c,volume)
            except (ValueError,TypeError,KeyError,OverflowError):
                bad+=1
    return out,bad

def indicators(bs,step):
    out={};prev=pc=None;n=0
    for t,(o,h,l,c,*_) in sorted(bs.items()):
        if prev is None or t-prev!=step:n=1;e9=e21=c;atr=h-l
        else:
            n+=1;e9+=.2*(c-e9);e21+=(c-e21)/11
            atr+=(max(h-l,abs(h-pc),abs(l-pc))-atr)/14
        if n>=105:out[t+step]=(e9,e21,atr)
        prev=t;pc=c
    return out

def prepare(t,minute,em,step,target,start,end):
    try:
        a,b=epoch(t["opened"]),epoch(t["closed"])
        if a<start-MAX_WINDOW or b>end or b<=a:return None,"outside_replay_coverage"
        if t["excursion"]["status"]!="complete_interior_lower_bound" or "large_excursion_requires_data_review" in t["data_quality_notes"]:
            return None,"unverified_price_path"
        sign={"LONG":1,"SHORT":-1}[t["direction"]]
        x=t["exposure"];p=t["entry"]["plan"];y=t["outcome"]
        entry=finite(x["average_fill_price"]);qty=finite(x["filled_contracts"])*finite(x["contract_value"])
        fee,gross,actual,sl,tp=map(finite,(y["fees"],y["gross_pnl"],y["net_before_funding"],p["stop_loss"],p["take_profit"]))
        if x.get("fill_notional") is None or min(entry,qty,sl,tp)<=0 or fee<0 or abs(gross-fee-actual)>1e-6:
            return None,"invalid_exposure_or_accounting"
        if sign*(entry-sl)<=0 or sign*(tp-entry)<=0:return None,"invalid_original_bracket"
        exit_avg=entry+sign*gross/qty
        if exit_avg<=0:return None,"invalid_exit"
        rate=fee/(qty*(entry+exit_avg));first=math.ceil(a/60)*60;last=math.floor(b/60)*60
        if last<=first or any(i not in minute for i in range(first,last,60)):return None,"missing_interior_minutes"
        if any((i//step)*step not in em for i in range(first,last,60)):return None,"ema_warmup_or_gap"
        target_at_entry=tp
        if target!="original":
            at_entry=em.get(math.floor(a/step)*step)
            if at_entry is None:return None,"ema_entry_warmup"
            target_at_entry=at_entry[1]
            if sign*(target_at_entry-entry)<=0:return None,"invalid_ema21_target_at_entry"
        if a!=first:
            boundary=minute.get(first-60)
            if boundary is None:return None,"missing_entry_boundary"
            _,h,l,_,*_=boundary
            if (l<=sl or h>=min(tp,target_at_entry)) if sign==1 else (h>=sl or l<=max(tp,target_at_entry)):
                return None,"ambiguous_entry_boundary"
        return dict(id=t["decision_id"],opened=t["opened"],closed=t["closed"],sign=sign,entry=entry,qty=qty,
                    rate=rate,actual=actual,first=first,last=last,sl=sl,tp=tp,target_at_entry=target_at_entry),None
    except (ValueError,TypeError,KeyError,ArithmeticError,OverflowError):
        return None,"missing_or_invalid_trade_fields"

def simulate(t,minute,em,step,variant,target):
    sign,entry,qty,rate,sl,tp=(t[k] for k in ("sign","entry","qty","rate","sl","tp"))
    initial=sl;activation=None;adjustments=0;dual=False;reason="time_cap";px=None
    prev_close=None;active=variant is not None and not variant[1]
    if variant is not None and target!="original":tp=t["target_at_entry"]
    for i in range(t["first"],t["last"],60):
        o,h,l,c,*_=minute[i]
        # Existing bracket takes priority at the next observed open.
        if sign*(o-sl)<=0:px=o;reason="stop_gap";break
        if sign*(o-tp)>=0:px=tp;reason="target_gap";break
        if variant is not None:
            buffer,delayed=variant
            ema9,ema21,atr=em[(i//step)*step]
            if target=="dynamic_ema21":
                tp=ema21
                if sign*(o-tp)>=0:px=o;reason="ema_target_crossed_at_update";break
            if delayed and not active and prev_close is not None:
                adverse=prev_close*(1-sign*2/10000)
                if sign*(adverse-entry)-rate*(entry+adverse)>=0:active=True
            if active:
                if activation is None:activation=i
                candidate=ema9-sign*buffer*atr
                new=max(sl,candidate) if sign==1 else min(sl,candidate)
                if sign*(new-sl)>0:sl=new;adjustments+=1
                if sign*(o-sl)<=0:px=o;reason="ema_crossed_at_update";break
        stop_hit=l<=sl if sign==1 else h>=sl
        target_hit=h>=tp if sign==1 else l<=tp
        if stop_hit:px=sl;reason="stop";dual=target_hit;break
        if target_hit:px=tp;reason="target";break
        prev_close=c
    if px is None:px=minute[t["last"]-60][3];i=t["last"]-60
    net={}
    for bp in COSTS:
        fill=px*(1-sign*bp/10000)
        net[str(bp)]=sign*(fill-entry)*qty-rate*(entry+fill)*qty
    return dict(id=t["id"],opened=t["opened"],closed=t["closed"],actual=t["actual"],net=net,reason=reason,
                dual_touch=dual,adjustments=adjustments,activated=activation is not None,initial_sl=initial,
                final_sl=sl,exit_price=px,exit_bar=i)

def metrics(vals):
    wins=[x for x in vals if x>0];losses=[x for x in vals if x<0]
    w=sum(wins);l=-sum(losses);eq=peak=dd=0
    for x in vals:eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
    return dict(net=round(sum(vals),6),wins=len(wins),losses=len(losses),breakeven=len(vals)-len(wins)-len(losses),
                expectancy=round(sum(vals)/len(vals),6) if vals else None,profit_factor=round(w/l,6) if l else None,
                average_win=round(w/len(wins),6) if wins else None,average_loss=round(l/len(losses),6) if losses else None,
                closed_pnl_drawdown_original_close_order=round(dd,6))

def compare(rows,baseline):
    rows=sorted(rows,key=lambda r:(r["closed"],r["id"]));n=len(rows)
    out=dict(n=n,actual_same_trades=metrics([r["actual"] for r in rows]),simulated={},delta_vs_fixed_bracket={},
             exits=dict(Counter(r["reason"] for r in rows)),activated=sum(r["activated"] for r in rows),
             adjusted=sum(r["adjustments"]>0 for r in rows),dual_touch_stop_first=sum(r["dual_touch"] for r in rows))
    for bp in map(str,COSTS):
        vals=[r["net"][bp] for r in rows];diff=[r["net"][bp]-baseline[r["id"]]["net"][bp] for r in rows]
        out["simulated"][bp]=metrics(vals)
        out["delta_vs_fixed_bracket"][bp]=dict(net=round(sum(diff),6),improved=sum(x>1e-8 for x in diff),
                 worse=sum(x< -1e-8 for x in diff),unchanged=sum(abs(x)<=1e-8 for x in diff))
    return out

def signatures(paths):
    return tuple((s.st_ino,s.st_size,s.st_mtime_ns) if (s:=p.stat()) else None for p in paths)

def run(root,learning,symbol,start,end,frames,target,expected_count=None,decision_id=None):
    check_window(start,end)
    if target not in ("original","fixed_ema21","dynamic_ema21") or any(f not in FRAMES for f in frames):raise ValueError("unsupported option")
    paths=[root/f for f in ("market.sqlite","orders.sqlite","decisions.sqlite")]+[learning/"learning.sqlite"]
    try:
        before=signatures(paths)
        report=trade_intelligence.report(root,symbol,learning)
        rows=[t for t in report["trades"] if start<=epoch(t["closed"])<end]
        if len({r["decision_id"] for r in rows})!=len(rows):return response(status="ambiguous_episode_identity")
        observed=len(rows);coverage=report.get("coverage",{})
        if expected_count is not None and observed!=expected_count:
            return response(status="cohort_count_mismatch",expected_count=expected_count,available_count=observed,coverage=coverage)
        if decision_id is not None:rows=[t for t in rows if t["decision_id"]==decision_id]
        if not rows:return response(status="no_matching_episodes",coverage=coverage)
        earliest=min(epoch(t["opened"]) for t in rows)
        earliest=max(earliest,start-MAX_WINDOW)
        # Bound the minute path to at most twice the requested maximum window plus warmup.
        first=math.floor(earliest/60)*60
        minute,bad=load_bars(root,symbol,"1m",max(0,first-106*60),end)
        results={}
        for frame in frames:
            step=FRAMES[frame]
            raw,invalid=(minute,bad) if step==60 else load_bars(root,symbol,frame,max(0,(first//step-106)*step),end)
            em=indicators(raw,step);eligible=[];skips=Counter()
            for t in rows:
                r,why=prepare(t,minute,em,step,target,start,end)
                if r:eligible.append(r)
                else:skips[why]+=1
            trials={name:[simulate(t,minute,em,step,var,target) for t in eligible] for name,var in VARIANTS.items()}
            baseline={r["id"]:r for r in trials["baseline"]}
            results[frame]=dict(eligible=len(eligible),excluded=dict(skips),invalid_candles=invalid,
                                summaries={name:compare(rs,baseline) for name,rs in trials.items()},details=trials)
        if before!=signatures(paths):return response(status="snapshot_changed_retry")
        return response(status="observed",symbol=symbol,window={"start":start,"end_exclusive":end},
                        target=target,available_count=observed,selected_count=len(rows),coverage=coverage,
                        snapshot_mtime_ns={p.name:sig[2] for p,sig in zip(paths,before)},frames=results,
                        limitations=LIMITATIONS)
    except (sqlite3.Error,OSError,ValueError,TypeError,KeyError,ArithmeticError) as e:
        return response(status="research_data_unavailable_or_invalid",error_type=type(e).__name__)

def register_backtests(mcp, *, data_dir, learning_dir):
    data=Path(data_dir).resolve();learning=Path(learning_dir).resolve()
    def root(symbol):
        if symbol not in MARKETS:raise ValueError("unsupported demo market")
        return data/symbol
    def execute(symbol,start,end,frames,target,expected_count,decision_id=None):
        if expected_count is not None:integer(expected_count,1,50)
        if decision_id is not None and (not isinstance(decision_id,str) or len(decision_id)!=64 or any(c not in "0123456789abcdef" for c in decision_id)):
            raise ValueError("invalid decision identity")
        return run(root(symbol),learning,symbol,start,end,frames,target,expected_count,decision_id)
    def compact(r):
        if "frames" in r:
            for f in r["frames"].values():f.pop("details",None)
        return r
    @mcp.tool()
    def historical_candles(symbol:Market,frame:Frame,start:int,end:int,limit:int=500,offset:int=0):
        """Read confirmed archived trade-price candles; bounded pagination, historical UTC epochs."""
        check_window(start,end);integer(limit,1,500);integer(offset,0,45000)
        if frame not in FRAMES:raise ValueError("unsupported frame")
        p=root(symbol)
        try:
            sig=signatures([p/"market.sqlite"])
            bars,bad=load_bars(p,symbol,frame,start,end)
            if sig!=signatures([p/"market.sqlite"]):return response(status="snapshot_changed_retry")
            items=sorted(bars.items());page=items[offset:offset+limit]
            return response(status="observed",symbol=symbol,frame=frame,available=len(items),invalid=bad,
                next_offset=offset+len(page) if offset+len(page)<len(items) else None,
                snapshot_mtime_ns=sig[0][2],candles=[dict(zip(("time","open","high","low","close","volume"),(t,*v))) for t,v in page])
        except (sqlite3.Error,OSError,ValueError,TypeError) as e:return response(status="research_data_unavailable_or_invalid",error_type=type(e).__name__)
    @mcp.tool()
    def ema_backtest(symbol:Market,frame:Frame,start:int,end:int,target:Target="original",expected_count:int|None=None):
        """Replay original entries with AI initial SL, monotonic EMA9/ATR trailing and optional EMA21 targets. Summaries only."""
        return compact(execute(symbol,start,end,[frame],target,expected_count))
    @mcp.tool()
    def trade_replay(symbol:Market,frame:Frame,start:int,end:int,decision_id:str,target:Target="original"):
        """Replay one attributed original trade with all eight EMA stop variants; no execution."""
        return execute(symbol,start,end,[frame],target,None,decision_id)
    @mcp.tool()
    def backtest_comparison(symbol:Market,start:int,end:int,target:Target="original",expected_count:int|None=None):
        """Compare matched fixed-bracket and eight adaptive EMA variants across six frames. Frame cohorts may differ."""
        return compact(execute(symbol,start,end,list(FRAMES),target,expected_count))
