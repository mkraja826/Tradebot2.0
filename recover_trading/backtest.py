"""Offline, chronological signal replay. No AI, credentials or order access."""
import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from tradebot.market_data_v3 import MARKETS, normalize
from tradebot.feature_snapshot_v3 import snapshot
from tradebot.bitcoin_strategies_v3 import scan_btc
from tradebot.gold_strategies_v3 import scan_gold
from .direction import direction_for, REGISTRY
from .regime import FAMILIES

STEP=300
HORIZONS=(900,3600,14400)
SCANNERS={"BTCUSD":scan_btc,"XAUTUSD":scan_gold}

def load_bars(database,symbol,start,end):
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        rows=db.execute("SELECT stamp,payload FROM samples WHERE symbol=? AND series='candle:5m' AND stamp>=? AND stamp<=? ORDER BY stamp",
                        (symbol,start,end)).fetchall()
    return {t:json.loads(raw) for t,raw in rows}

def outcome(bars,at,horizon,side,cost_bps):
    # Full extra candle of latency, then open-to-open return. No future
    # candle is passed to the rule evaluator. Missing intervals are not filled.
    entry_at=at+STEP
    exit_at=entry_at+horizon
    expected=range(entry_at,exit_at+STEP,STEP)
    try:
        rows=normalize([bars[t] for t in expected],"5m",as_of=exit_at+STEP,count=len(expected))
    except (KeyError,ValueError):
        return None
    entry,exit=rows[0]["open"],rows[-1]["open"]
    gross=(exit/entry-1)*10000*(1 if side=="LONG" else -1)
    return {"entry_at":entry_at,"exit_at":exit_at,"entry":entry,"exit":exit,
            "gross_bps":gross,"net_bps":gross-cost_bps}

def summarize(rows):
    n=len(rows)
    return {"samples":n,"wins":sum(r["net_bps"]>0 for r in rows),
            "losses":sum(r["net_bps"]<0 for r in rows),
            "breakeven":sum(r["net_bps"]==0 for r in rows),
            "win_rate":sum(r["net_bps"]>0 for r in rows)/n if n else None,
            "mean_gross_bps":sum(r["gross_bps"] for r in rows)/n if n else None,
            "mean_net_bps":sum(r["net_bps"] for r in rows)/n if n else None}

def replay(database,symbol,start,end,*,stride=900,cost_bps=15.0,split=None,
           make_snapshot=snapshot):
    if symbol not in MARKETS or any(type(x) is not int or x%STEP for x in (start,end,stride)) or not 0<start<end or stride<STEP:
        raise ValueError("invalid replay window")
    if not math.isfinite(cost_bps) or cost_bps<0:
        raise ValueError("invalid cost assumption")
    split=(start+int((end-start)*0.7))//STEP*STEP if split is None else split
    if type(split) is not int or split%STEP or not start<split<end:
        raise ValueError("invalid split")
    bars=load_bars(database,symbol,start,end)
    seen=set(); busy={}; coverage=Counter(); regimes=Counter(); counts=Counter()
    results=defaultdict(list); events=[]
    for at in range(start,end,stride):
        data=make_snapshot(database,at,symbols=(symbol,),candle_as_of=at)
        report=SCANNERS[symbol](data)
        report["market_context"]=data["markets"][symbol]
        decision=direction_for(report)
        regimes[decision["regime"]["regime"]]+=1
        for ident in {r["id"] for r in report["results"] if r["status"] in ("triggered","no_signal")}:
            coverage[ident]+=1
        counts["snapshots"]+=1
        counts["direction_"+decision["direction"]]+=1
        # One distinct rule per evaluation. Conflicting timeframes abstain;
        # retain the original candle IDs so an old persistent signal is not replayed.
        candidates=[]
        for side in ("LONG","SHORT"):
            for vote in decision["votes"][side]:
                keys={(s["id"],s["frame"],s["direction"],s["closed_at"]) for s in report["signals"] if s["id"]==vote["id"] and s["direction"]==side}
                if keys-seen:
                    candidates.append((vote["id"],side))
                seen.update(keys)
        # Fixed periodic ensemble hypothesis, not a simulation of AI/order dedup.
        old="LONG" if decision["long_votes"]>decision["short_votes"] else "SHORT" if decision["short_votes"]>decision["long_votes"] else "NEUTRAL"
        candidates.extend((name,side) for name,side in (("ensemble_v1",old),("ensemble_v2",decision["direction"])) if side!="NEUTRAL")
        partition="development" if at<split else "holdout"
        boundary=split if at<split else end
        for ident,side in candidates:
            for horizon in HORIZONS:
                # No overlapping position windows per hypothesis/horizon.
                # Purge samples whose exit candle is not fully inside the partition.
                if at+STEP+horizon+STEP>boundary:
                    counts["boundary_excluded"]+=1
                    continue
                key=(ident,horizon)
                if at<busy.get(key,0):
                    counts["overlap_excluded"]+=1
                    continue
                result=outcome(bars,at,horizon,side,cost_bps)
                if result is None:
                    counts["missing_exit_or_entry"]+=1
                    continue
                busy[key]=result["exit_at"]
                result.update(rule_id=ident,family=FAMILIES.get(ident,"ensemble"),side=side,
                              horizon_s=horizon,regime=decision["regime"]["regime"],
                              partition=partition,decision_at=at)
                results[(ident,horizon,partition,"all")].append(result)
                results[(ident,horizon,partition,result["regime"])].append(result)
                events.append(result)
    rows=[{"rule_id":k[0],"family":FAMILIES.get(k[0],"ensemble"),"horizon_s":k[1],
           "partition":k[2],"regime":k[3],**summarize(v)} for k,v in sorted(results.items())]
    rules,deferred=REGISTRY[symbol]
    return {"version":"historical-replay-v1","symbol":symbol,"start":start,"end":end,"split":split,
            "stride_s":stride,"cost_bps_round_trip":cost_bps,"horizons_s":HORIZONS,
            "entry_delay_s":STEP,"counts":dict(counts),"regimes":dict(regimes),
            "coverage":[{"id":r.id,"family":FAMILIES[r.id],"evaluable_snapshots":coverage[r.id]} for r in rules],
            "deferred":sorted(deferred),"results":rows,"events":events,
            "limitations":["fixed-horizon unleveraged price returns, not AI trade P&L",
                "cost assumption is illustrative, funding and liquidation excluded",
                "no macro reconstruction; missing feeds remain unavailable",
                "different strategy outcomes may overlap; no claim of statistical independence",
                "holdout is chronological, no parameters fitted or deployed"]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",required=True)
    p.add_argument("--symbol",required=True,choices=MARKETS)
    p.add_argument("--start",required=True,type=int)
    p.add_argument("--end",required=True,type=int)
    p.add_argument("--stride",type=int,default=900)
    p.add_argument("--cost-bps",type=float,default=15)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    if Path(a.output).resolve()==Path(a.database).resolve():
        p.error("output must be separate from database")
    result=replay(a.database,a.symbol,a.start,a.end,stride=a.stride,cost_bps=a.cost_bps)
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"symbol":a.symbol,"counts":result["counts"],"evaluable_rules":sum(r["evaluable_snapshots"]>0 for r in result["coverage"]),"outcome_count":len(result["events"]),"output":a.output}))

if __name__=="__main__":
    main()
