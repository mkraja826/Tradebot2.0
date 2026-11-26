"""Offline Gold entry evidence and descriptive cohort analysis; no execution or AI."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from .performance import dec, read_performance
from .regime import FAMILIES
from .trade_intelligence import sql, obj, mapping, exposure
from .decision_review import read_review

VERSION="gold-entry-intelligence-v1"
SYMBOL="XAUTUSD"

def bps(a,b):
    a,b=dec(a),dec(b)
    return float((a-b)/b*10000) if a is not None and b is not None and b>0 else None

def relation(direction,bias):
    if direction not in ("LONG","SHORT") or bias not in ("LONG","SHORT"):return "unknown_or_neutral"
    return "aligned" if direction==bias else "opposed"

def evidence(context,created):
    """Only archived decision-time data. No later candles or trade outcomes."""
    if context.get("symbol")!=SYMBOL or type(created) is not int:
        return {"status":"invalid_context"}
    cutoff=context.get("as_of")
    if type(cutoff) is not int or cutoff<=0 or cutoff>created+1:
        return {"status":"invalid_cutoff"}
    d=mapping(context.get("direction_engine"));side=d.get("direction")
    regime=mapping(d.get("regime"));groups={"LONG":set(),"SHORT":set()}
    rejected=0
    for s in context.get("signals",[]):
        s=mapping(s);rule=s.get("id");at=s.get("closed_at");direction=s.get("direction")
        if (not isinstance(rule,str) or not rule.startswith("G") or rule not in FAMILIES
            or type(at) is not int or not 0<at<=cutoff or direction not in groups):
            rejected+=1;continue
        groups[direction].add(rule)
    conflicting=groups["LONG"]&groups["SHORT"]
    families={k:sorted({FAMILIES[i] for i in ids-conflicting}) for k,ids in groups.items()}
    supporting=families.get(side,[])
    opposite=families.get("SHORT" if side=="LONG" else "LONG" if side=="SHORT" else "",[])
    q=mapping(mapping(context.get("demo_account")).get("decision_quote"))
    bid,ask=dec(q.get("best_bid")),dec(q.get("best_ask"))
    ts=q.get("timestamp_us")
    valid_quote=(q.get("status")=="fresh_book" and bid is not None and ask is not None
        and 0<bid<=ask and type(ts) is int and 0<=created*1000000+999999-ts<=31000000)
    ref=ask if valid_quote and side=="LONG" else bid if valid_quote and side=="SHORT" else None
    frames=mapping(mapping(context.get("market")).get("frames"))
    levels={}
    for name in ("5m","15m","1h","4h"):
        f=mapping(frames.get(name));closed=f.get("closed_at")
        if f.get("status")!="ready" or type(closed) is not int or not 0<closed<=cutoff:
            levels[name]={"status":"unavailable_or_future"};continue
        feat=mapping(f.get("features"));c=mapping(f.get("candle"))
        ema50,ema200=dec(feat.get("ema50")),dec(feat.get("ema200"))
        bias="LONG" if ema50 is not None and ema200 is not None and ema50>ema200 else "SHORT" if ema50 is not None and ema200 is not None and ema50<ema200 else None
        levels[name]={"status":"observed","closed_at":closed,"ema_alignment":relation(side,bias),
            "adx":str(dec(feat.get("adx14"))) if dec(feat.get("adx14")) is not None else None,
            "atr_pct":str(dec(feat.get("atr14_pct"))) if dec(feat.get("atr14_pct")) is not None else None,
            "quote_vs_vwap_bps":bps(ref,feat.get("utc_day_vwap")),
            "quote_vs_ema20_bps":bps(ref,feat.get("ema20")),
            "quote_vs_swing_high_bps":bps(ref,feat.get("confirmed_swing_high")),
            "quote_vs_swing_low_bps":bps(ref,feat.get("confirmed_swing_low")),
            "quote_vs_candle_close_bps":bps(ref,c.get("close"))}
    return {"version":VERSION,"status":"observed","as_of":cutoff,"direction":side,
        "regime":regime.get("regime","unknown"),"volatility":regime.get("volatility","unknown"),
        "higher_timeframe_alignment":relation(side,regime.get("trend_bias")),
        "supporting_families":supporting,"opposing_families":opposite,
        "shared_families":sorted(set(supporting)&set(opposite)),
        "conflicting_rules":sorted(conflicting),"discarded_signal_records":rejected,
        "quote_status":"archived_fresh_book" if valid_quote else "unavailable_or_unverified",
        "estimated_entry_quote":str(ref) if ref is not None else None,
        "spread_bps":float((ask-bid)/((ask+bid)/2)*10000) if valid_quote else None,
        "frames":levels,"execution_effect":"none"}

def plan_economics(context,result,card):
    """Scenarios only: price distances minus assumed round-trip costs, not probabilities."""
    ref=dec(card.get("estimated_entry_quote"));sl=dec(result.get("stop_loss"));tp=dec(result.get("take_profit"))
    sign=1 if result.get("side")=="buy" else -1 if result.get("side")=="sell" else 0
    out={"status":"unavailable","assumed_round_trip_cost_bps":[5,15,30],"scenarios":[]}
    if not sign or any(x is None or x<=0 for x in (ref,sl,tp)):return out
    stop=sign*(ref-sl)/ref*10000;target=sign*(tp-ref)/ref*10000
    out.update(status="observed_plan_not_verified_execution",stop_bps=float(stop),target_bps=float(target),
        orientation_consistent=stop>0 and target>0)
    if stop>0 and target>0:
        for cost in (5,15,30):
            out["scenarios"].append({"assumed_cost_bps":cost,"net_target_bps":float(target-cost),
                "net_stop_loss_bps":float(stop+cost),
                "break_even_win_rate":float((stop+cost)/(stop+target)) if target>cost else None})
    return out

def report(root):
    root=Path(root);p=read_performance(root,SYMBOL);rv=read_review(root,SYMBOL,p)
    records=sql(root/"decisions.sqlite","SELECT id,model,status,created,context,result FROM decisions WHERE symbol=? ORDER BY created,id",(SYMBOL,))
    result={"version":VERSION,"symbol":SYMBOL,"execution_effect":"none","validation":"descriptive_only",
        "status":"unavailable" if records is None else "observed","trades":[],"cohorts":[]}
    if records is None:return result
    by_id={x[0]:x for x in records};by_review={x.get("id"):x for x in rv.get("recent",[])}
    buckets=defaultdict(list)
    for e in p.get("recent_episodes",[]):
        if e.get("attribution")!="single_recover_entry_order":continue
        rec=by_id.get(e.get("decision_id"))
        if not rec or rec[2]!="proposed":continue
        ident,model,status,created,raw_c,raw_r=rec;c=obj(raw_c);r=obj(raw_r)
        if r.get("symbol")!=SYMBOL or r.get("action")!="trade":continue
        card=evidence(c,created)
        if card["status"]!="observed":continue
        net=dec(e.get("net_before_funding"))
        if net is None:continue
        result["trades"].append({"decision_id":ident,"model":model,"closed":e.get("closed"),"entry_evidence":card,
            "plan_economics":plan_economics(c,r,card),"exposure":exposure(c,r,by_review.get(ident,{})),
            "observed_net_before_funding":str(net)})
        for key,value in (("regime",card["regime"]),("volatility",card["volatility"]),
                          ("trend_alignment",card["higher_timeframe_alignment"]),
                          ("supporting_family_count",str(len(card["supporting_families"]))),
                          ("opposing_family_count",str(len(card["opposing_families"])))):
            buckets[(key,value)].append(net)
    for (key,value),ns in sorted(buckets.items()):
        result["cohorts"].append({"dimension":key,"value":value,"samples":len(ns),"wins":sum(n>0 for n in ns),
            "net_before_funding":str(sum(ns)),"mean_net_before_funding":str(sum(ns)/len(ns))})
    expected=mapping(p.get("recover_attributed")).get("closed_episodes")
    result["coverage"]={"expected_attributed_episodes":expected,"reported_episodes":len(result["trades"]),
        "complete_window":type(expected) is int and expected==len(result["trades"])}
    result["limitations"]=["Archived observations only; no future features and no live decision changes.",
        "Cohorts overlap across dimensions; no causal attribution, statistical ranking or probability calibration.",
        "Signals within a family and between families can correlate; family counts are not independent confirmations.",
        "Cost scenarios are hypothetical; actual fill, funding and AI costs are not inferred.",
        "Only bounded recent attributed closed episodes; actual monetary exposure may be missing."]
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument("--data-dir",default="/var/lib/recover-trading/demo")
    a=p.parse_args();print(json.dumps(report(Path(a.data_dir)/SYMBOL),allow_nan=False,indent=2))
if __name__=="__main__":main()
