"""Matched exit-only replay of a frozen liquidation V1 cohort; offline/read-only."""
import argparse
import json
import math
from pathlib import Path
from collections import Counter

from .liquidation_ema9 import VERSION as V1, FEE_BPS, HOLD_MINUTES, ENTRY_SLIPPAGE_BPS
from .tb2_backtest_tools import FRAMES, VARIANTS, COSTS, check_window, indicators, load_bars, metrics, simulate, signatures

VERSION = "liquidation-ema9-multiframe-v2"


def frozen(report):
    if (report.get("version") != V1 or report.get("symbol") != "BTCUSD"
            or report.get("status") != "observed" or report.get("execution_effect") != "none"):
        raise ValueError("observed BTC liquidation V1 report required")
    start, split, end = (report[k] for k in ("start", "split", "end"))
    check_window(start, end)
    if type(split) is not int or not start < split < end:
        raise ValueError("invalid partition")
    a = report["assumptions"]
    if (a["round_trip_fee_bps"], a["entry_slippage_bps"], a["hold_minutes"], a["ema_variant"]) != (FEE_BPS, ENTRY_SLIPPAGE_BPS, HOLD_MINUTES, "15m V8"):
        raise ValueError("unexpected assumptions")
    rows = []
    reserved_until = 0
    for r in sorted(report["trades"], key=lambda r:r["entry_at"]):
        t, obs = r["entry_at"], r["observed_ms"]
        last = t + HOLD_MINUTES * 60
        part = "development" if obs < split * 1000 else "holdout"
        sign = {"LONG":1,"SHORT":-1}[r["direction"]]
        entry, sl, tp = (float(r[k]) for k in ("entry_price","initial_stop","target"))
        kind = "reversal" if r["direction"] == r["liquidation_side"] else "continuation"
        if (type(t) is not int or type(obs) is not int or t % 60
                or not start * 1000 <= obs < t * 1000 <= end * 1000
                or t < reserved_until or last > (split if part == "development" else end)
                or r["partition"] != part or r["liquidation_side"] not in ("LONG","SHORT") or r["kind"] != kind
                or not all(math.isfinite(x) and x > 0 for x in (entry,sl,tp))
                or sign * (entry-sl) <= 0 or sign * (tp-entry) <= 0):
            raise ValueError("invalid frozen entry")
        reserved_until = last
        rows.append((r,dict(id=str(t), opened=t, closed=last, first=t, last=last, sign=sign,
                            entry=entry,qty=1/entry,rate=FEE_BPS/20000,sl=sl,tp=tp,
                            target_at_entry=tp,actual=None)))
    if not rows:
        raise ValueError("empty frozen cohort")
    return rows


def same_result(a,b):
    return (a["reason"] == b["reason"] and a["exit_bar"] == b["exit_bar"]
            and all(math.isclose(a["net"][str(c)],b["net"][str(c)],rel_tol=1e-9,abs_tol=1e-10) for c in COSTS))


def summarize(rows, ids):
    selected = [r for r in rows if r["id"] in ids]
    fixed = [r["baseline"] for r in selected]
    out = {}
    for variant in VARIANTS:
        if variant == "baseline":
            continue
        trials = [r[variant] for r in selected]
        costs = {}
        for c in map(str,COSTS):
            a = [r["net"][c]*10000 for r in fixed]
            b = [r["net"][c]*10000 for r in trials]
            d = [y-x for x,y in zip(a,b)]
            costs[c] = dict(fixed_bps=metrics(a),adaptive_bps=metrics(b),
                improvement_bps=round(sum(d),6),improved=sum(x>1e-7 for x in d),
                worse=sum(x< -1e-7 for x in d),unchanged=sum(abs(x)<=1e-7 for x in d))
        out[variant] = dict(n=len(trials),activated=sum(r["activated"] for r in trials),
            adjusted=sum(r["adjustments"]>0 for r in trials),
            exits=dict(Counter(r["reason"] for r in trials)),costs=costs)
    return out


def analyze(report, minute, maps):
    rows = frozen(report)
    mismatches = []
    fixed = {}
    for r,t in rows:
        if any(i not in minute for i in range(t["first"],t["last"],60)):
            mismatches.append({"id":t["id"],"reason":"missing_minute_path"})
            continue
        expected = minute[t["first"]][0]*(1+t["sign"]*ENTRY_SLIPPAGE_BPS/10000)
        if not math.isclose(expected,t["entry"],rel_tol=1e-9):
            mismatches.append({"id":t["id"],"reason":"entry_price_changed"})
            continue
        b = simulate(t,minute,{},60,None,"original")
        if not same_result(b,r["fixed"]):
            mismatches.append({"id":t["id"],"reason":"fixed_baseline_changed"})
            continue
        em = maps.get("15m",{})
        if any(i//900*900 not in em for i in range(t["first"],t["last"],60)):
            mismatches.append({"id":t["id"],"reason":"missing_V1_15m_coverage"})
            continue
        v8 = simulate(t,minute,em,900,VARIANTS["V8"],"original")
        if not same_result(v8,r["adaptive"]):
            mismatches.append({"id":t["id"],"reason":"V1_adaptive_changed"})
            continue
        fixed[t["id"]] = b
    base = dict(version=VERSION,execution_effect="none",symbol="BTCUSD",
                window={k:report[k] for k in ("start","split","end")},frozen_count=len(rows))
    if mismatches:
        return dict(**base,status="cohort_reproduction_failed",mismatches=mismatches)
    by_frame = {}
    for frame,step in FRAMES.items():
        em = maps.get(frame,{})
        entries = []
        excluded = []
        for r,t in rows:
            if any(i//step*step not in em for i in range(t["first"],t["last"],60)):
                excluded.append(t["id"])
                continue
            trials = {v:simulate(t,minute,em,step,p,"original") for v,p in VARIANTS.items() if v!="baseline"}
            entries.append(dict(id=t["id"],kind=r["kind"],partition=r["partition"],
                                baseline=fixed[t["id"]],**trials))
        by_frame[frame]=(entries,excluded)
    nonempty = [{r["id"] for r in entries} for entries,_ in by_frame.values() if entries]
    common = set.intersection(*nonempty) if nonempty else set()
    frames = {}
    for frame,(entries,excluded) in by_frame.items():
        groups = {}
        for partition in ("all","development","holdout"):
            for kind in ("all","reversal","continuation"):
                ids = {r["id"] for r in entries if (partition=="all" or r["partition"]==partition)
                       and (kind=="all" or r["kind"]==kind)}
                groups[partition+"_"+kind] = summarize(entries,ids)
        frames[frame] = dict(eligible=len(entries),excluded_ids=excluded,groups=groups,
                             common_nonempty_frames=summarize(entries,common),details=entries)
    return dict(**base,status="observed",baseline_reproduced=len(fixed),
                common_ids=sorted(common),common_frames=[f for f,(e,_) in by_frame.items() if e],
                frames=frames,limitations=[
                    "Frozen V1 entries, brackets, 60-minute reservation and costs; no new entries.",
                    "All 48 variants exploratory; neither development nor previously inspected holdout is independent.",
                    "Frame coverage differs; compare only matched cohorts or explicitly identified common subset.",
                    "105 contiguous completed candles required for EMA9/ATR; missing coverage is not a losing trade.",
                    "V1 Bybit reference observations and Delta candle proxies; no mark trigger, funding, leverage, AI cost or actual fills."
                ])


def run(root,report):
    root=Path(root).resolve()
    rows=frozen(report)
    start,end=report["start"],report["end"]
    before=signatures([root/"market.sqlite"])
    maps={};bad={};minute={}
    for frame,step in FRAMES.items():
        bs,bad[frame]=load_bars(root,"BTCUSD",frame,max(0,start//step*step-106*step),end)
        maps[frame]=indicators(bs,step)
        if frame=="1m":minute=bs
    result=analyze(report,minute,maps)
    if before!=signatures([root/"market.sqlite"]):
        return dict(version=VERSION,execution_effect="none",status="snapshot_changed_retry")
    result["invalid_candles"]=bad
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--market-root",required=True)
    p.add_argument("--v1-report",required=True)
    a=p.parse_args()
    try:
        report=json.loads(Path(a.v1_report).read_text())
        result=run(a.market_root,report)
    except (OSError,ValueError,TypeError,KeyError,ArithmeticError) as exc:
        result=dict(version=VERSION,execution_effect="none",status="research_data_unavailable_or_invalid",error_type=type(exc).__name__)
    print(json.dumps(result,allow_nan=False))

if __name__=="__main__":
    main()
