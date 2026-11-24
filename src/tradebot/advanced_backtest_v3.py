"""Advanced historical scenarios, not a broker or AI trading simulator."""
from math import isfinite
from statistics import mean
from collections import Counter,defaultdict
from contextlib import closing
from pathlib import Path
import json,sqlite3
from tradebot.market_data_v3 import MARKETS,FRAMES,normalize
from tradebot.feature_snapshot_v3 import snapshot
from tradebot.bitcoin_strategies_v3 import scan_btc
from tradebot.gold_strategies_v3 import scan_gold
from tradebot.regime_learning_v3 import classify

HORIZONS=(15,60,240)
COSTS=(5,10,20)
def simulate(bars,side,atr=None):
    """Conservative stop first on ambiguous bars, adverse opening gaps at open."""
    if side not in ("LONG","SHORT") or not bars: raise ValueError("invalid_scenario")
    entry=bars[0]["open"]; sign=1 if side=="LONG" else -1
    if atr is not None and (not isfinite(atr) or not 0<atr<entry/2): raise ValueError("invalid_atr")
    sl=entry-sign*atr if atr is not None else None
    tp=entry+sign*2*atr if atr is not None else None
    price=bars[-1]["close"]; reason="time_exit"; ambiguous=False
    if atr is not None:
        for b in bars:
            o,h,l=b["open"],b["high"],b["low"]
            if (o<=sl if sign==1 else o>=sl):
                price=o; reason="stop_gap"; break
            if (o>=tp if sign==1 else o<=tp):
                price=tp; reason="target_gap"; break
            stop=l<=sl if sign==1 else h>=sl
            target=h>=tp if sign==1 else l<=tp
            if stop:
                price=sl; reason="stop"; ambiguous=target; break
            if target:
                price=tp; reason="target"; break
    return {"gross_return_pct":100*sign*(price-entry)/entry,"exit_reason":reason,"ambiguous_bar":ambiguous}

def metrics(rows):
    gross=[x["gross_return_pct"] for x in rows]
    result={"samples":len(rows),"exit_reasons":dict(Counter(x["exit_reason"] for x in rows)),
            "ambiguous_bars":sum(x["ambiguous_bar"] for x in rows),"cost_scenarios":{}}
    for c in COSTS:
        vals=[x-c/100 for x in gross]
        total=peak=dd=0.
        for v in vals:
            total+=v; peak=max(peak,total); dd=max(dd,peak-total)
        result["cost_scenarios"][str(c)]={"positive":sum(x>0 for x in vals),"mean_pct":mean(vals) if vals else None,
             "sequence_drawdown_pct_points":dd if vals else None}
    return result

def handle_signal(db,s,t,end,market,sig,groups,last,counts):
    side=sig["direction"]; regime=classify({"market":market},sig)
    atr=market["frames"][sig["frame"]]["features"].get("atr14")
    for h in HORIZONS:
        start=t+300; finish=start+h*60
        k=(sig["id"],sig["frame"],side,h)
        if finish>end or start<last.get(k,0):
            counts["overlap_or_boundary"]+=1; continue
        raw=db.execute("SELECT payload FROM samples WHERE symbol=? AND series='candle:5m' AND stamp>=? AND stamp<? ORDER BY stamp",(s,start,finish))
        try: bars=normalize([json.loads(r[0]) for r in raw],"5m",as_of=finish,count=h//5)
        except ValueError: counts["missing_window"]+=1; continue
        last[k]=finish
        entry=bars[0]["open"]; high=max(b["high"] for b in bars); low=min(b["low"] for b in bars)
        mfe=100*(high/entry-1) if side=="LONG" else 100*(1-low/entry)
        mae=100*(1-low/entry) if side=="LONG" else 100*(high/entry-1)
        groups[k+("fixed",)].append(dict(simulate(bars,side),regime=regime,
            favorable_excursion_pct=max(0,mfe),adverse_excursion_pct=max(0,mae)))
        if type(atr) in (int,float) and isfinite(atr) and 0<atr<bars[0]["open"]/2:
            groups[k+("atr_bracket",)].append(dict(simulate(bars,side,atr),regime=regime))
        else: counts["missing_atr"]+=1

def regimes(groups):
    # Aggregate descriptive return distributions, not a chronological portfolio.
    g=defaultdict(list)
    for k,rows in groups.items():
        for r in rows:
            g[(k[3],k[4],r["regime"]["trend"])].append(r["gross_return_pct"])
    return [dict(horizon=k[0],scenario=k[1],trend=k[2],samples=len(v),
                 mean_gross_pct=mean(v),positive_after_10bps=sum(x>.1 for x in v)) for k,v in sorted(g.items())]

def replay(database,*,start,end):
    if start>=end or start%300 or end%300 or end-start>12*3600: raise ValueError("invalid_window")
    out={"mode":"advanced_historical_scenarios","start":start,"end":end,"markets":{},
         "horizons_minutes":HORIZONS,"cost_bps":COSTS,"bracket":"1 ATR stop / 2 ATR target from signal frame",
         "warning":"Fixed scenarios, no actual trades, funding or leverage. Overlapping groups are correlated. No parameter fitting.",
         "orders_submitted":0,"paid_ai_requests":0,"execution_authorized":False}
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        for s,scan in zip(MARKETS,(scan_btc,scan_gold)):
            groups=defaultdict(list); last={}; evals=Counter(); rules=set()
            for t in range(start,end,300):
                snap=snapshot(database,t,symbols=(s,)); market=snap["markets"][s]; a=scan(snap)
                for r in a["results"]:
                    if t%FRAMES[r["frame"]]: continue
                    evals["evaluated"]+=1
                    if r["status"]=="unavailable": evals["unavailable"]+=1
                    else: rules.add(r["id"])
                for sig in a["signals"]:
                    if sig["closed_at"]!=t: continue
                    evals["signals"]+=1
                    handle_signal(db,s,t,end,market,sig,groups,last,evals)
            out["markets"][s]={"coverage":dict(evals),"evaluable_rules":sorted(rules),
                "groups":[dict(rule_id=k[0],frame=k[1],side=k[2],horizon=k[3],scenario=k[4],**metrics(v))
                          for k,v in sorted(groups.items())],"regimes":regimes(groups)}
    return out
