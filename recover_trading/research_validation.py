"""Offline integration audit of staged intelligence modules against SQLite copies."""
import argparse
import json
import sqlite3
import tempfile
import time
from collections import Counter
from contextlib import closing
from pathlib import Path
from . import (trade_intelligence, gold_entry_intelligence, capital_intelligence,
               position_intelligence, cost_intelligence, regime_intelligence, learning_intelligence)
from .performance import read_performance, dec, stamp

VERSION="research-validation-v1"
SYMBOLS=("BTCUSD","XAUTUSD")
FILES=("decisions.sqlite","orders.sqlite","market.sqlite","signal_research.sqlite")

def copy_db(source,destination,timeout=15):
    """SQLite online backup, not raw copying a potentially WAL-backed DB."""
    if not source.is_file():return {"status":"missing"}
    start=time.monotonic()
    def progress(status,remaining,total):
        if time.monotonic()-start>timeout:raise TimeoutError("backup timeout")
    try:
        with closing(sqlite3.connect(source.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as src:
            src.execute("PRAGMA query_only=ON")
            with closing(sqlite3.connect(destination,timeout=2)) as dst:
                src.backup(dst,pages=128,progress=progress,sleep=0.02)
        return {"status":"copied","bytes":destination.stat().st_size}
    except (sqlite3.Error,OSError,TimeoutError) as exc:
        destination.unlink(missing_ok=True)
        return {"status":"copy_failed","error_type":type(exc).__name__}

def call(fn,*args):
    try:
        result=fn(*args)
        # Also check JSON serialization before accepting the report.
        json.dumps(result,allow_nan=False)
        return result
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError,sqlite3.Error,OSError) as exc:
        return {"status":"report_error","error_type":type(exc).__name__}

def key(row):
    return row.get("decision_id"),row.get("closed")

def audit_rows(expected,rows,extract):
    counts=Counter();seen=set()
    for row in rows:
        k=key(row)
        if k in seen:counts["duplicate"]+=1;continue
        seen.add(k)
        if k not in expected:counts["unexpected_episode"]+=1;continue
        a,b=dec(extract(row)),dec(expected[k].get("net_before_funding"))
        if a is None or b is None or a!=b:counts["pnl_mismatch"]+=1
    counts["missing_episode"]=len(set(expected)-seen)
    return {"expected":len(expected),"reported":len(rows),"issues":dict(counts),
        "status":"no_sample" if not expected and not rows else
            "consistent" if not any(counts.values()) else "incomplete_or_inconsistent"}

def validate_market(root,learning_dir,symbol,start,split,end,rates=None,plan=None):
    p=call(read_performance,root,symbol)
    episodes=[r for r in p.get("recent_episodes",[]) if r.get("attribution")=="single_recover_entry_order"]
    expected={key(r):r for r in episodes}
    window={}
    for k,r in expected.items():
        t=stamp({"created_at":r.get("closed")})
        if t is not None and start<=t.timestamp()<end:window[k]=r
    reports={
        "trade":call(trade_intelligence.report,root,symbol,learning_dir),
        "capital":call(capital_intelligence.report,root,symbol),
        "position":call(position_intelligence.report,root,symbol),
        "cost":call(cost_intelligence.report,root,symbol,start,end,rates),
        "regime":call(regime_intelligence.report,root,symbol,split,end)}
    if symbol=="XAUTUSD":reports["gold_entry"]=call(gold_entry_intelligence.report,root)
    rows=learning_intelligence.read_rows(Path(learning_dir)/"learning.sqlite",symbol)
    reports["learning"]=call(learning_intelligence.feedback,symbol,rows,end)
    if plan is not None:
        reports["learning_experiment"]=call(learning_intelligence.evaluate,plan,rows,end)
    extracts={"trade":lambda r:r.get("outcome",{}).get("net_before_funding"),
        "capital":lambda r:r.get("allocation",{}).get("observed_net_before_funding"),
        "position":lambda r:r.get("net_before_funding"),"cost":lambda r:r.get("net_before_funding"),
        "gold_entry":lambda r:r.get("observed_net_before_funding")}
    checks={name:audit_rows(window if name=="cost" else expected,reports[name].get("trades",[]),extract)
        for name,extract in extracts.items() if name in reports}
    counts=p.get("recover_attributed") or {}
    expected_total=counts.get("closed_episodes")
    coverage_complete=type(expected_total) is int and expected_total==len(episodes) and len(expected)==len(episodes)
    issues=[]
    if p.get("status")!="reconciled_subset":issues.append("baseline_not_reconciled")
    if not coverage_complete:issues.append("bounded_or_duplicate_baseline")
    if not expected:issues.append("no_attributed_trades")
    if any(v["status"]!="consistent" for v in checks.values()):issues.append("module_coverage_or_pnl_check")
    for name,r in reports.items():
        if r.get("execution_effect")!="none":issues.append(name+"_execution_effect_unverified")
        if r.get("status") in (None,"report_error","unavailable","journal_unavailable","unavailable_or_invalid_journal"):
            issues.append(name+"_unavailable")
    if reports["learning"].get("status")!="observations_available":issues.append("prior_learning_evidence_missing")
    if not reports["regime"].get("groups"):issues.append("regime_samples_missing")
    if not reports["cost"].get("ai_usage",{}).get("entry_journal_available") or not reports["cost"].get("ai_usage",{}).get("management_journal_available"):
        issues.append("ai_usage_journal_missing")
    return {"symbol":symbol,"baseline_status":p.get("status"),"baseline":counts,
        "baseline_recent_attributed":len(expected),"baseline_full_history_available":coverage_complete,
        "report_statuses":{k:v.get("status") for k,v in reports.items()},"checks":checks,"issues":issues,
        "status":"accounting_checks_consistent" if not issues else "review_required",
        "data_quality_counts":reports["trade"].get("data_quality_counts"),
        "retention_counts":reports["position"].get("retention_counts"),
        "matched_management_actions":reports["position"].get("matched_management_actions"),
        "exchange_costs":reports["cost"].get("exchange_costs"),
        "ai_usage":reports["cost"].get("ai_usage"),
        "regime_group_count":len(reports["regime"].get("groups",[])),
        "learning_observation_count":len(reports["learning"].get("observations",[])),
        "validated_lessons":[],
        "learning_experiment_status":reports.get("learning_experiment",{}).get("status")}

def run(data_dir,learning_dir,start,split,end,rates=None,plans=None):
    if any(type(v) is not int for v in (start,split,end)) or not 0<=start<split<end<=int(time.time()):
        raise ValueError("require ordered historical UTC cutoffs")
    data_dir=Path(data_dir);learning_dir=Path(learning_dir);plans=plans or {}
    began=int(time.time())
    with tempfile.TemporaryDirectory(prefix="recover-audit-") as tmp:
        root=Path(tmp);copies={}
        l=root/"learning";l.mkdir()
        copies["learning"]=copy_db(learning_dir/"learning.sqlite",l/"learning.sqlite")
        for s in SYMBOLS:
            d=root/s;d.mkdir()
            copies[s]={f:copy_db(data_dir/s/f,d/f) for f in FILES}
        markets=[validate_market(root/s,l,s,start,split,end,rates,plans.get(s)) for s in SYMBOLS]
    copied=all(v["status"]=="copied" for v in [copies["learning"],*(v for s in SYMBOLS for v in copies[s].values())])
    return {"version":VERSION,"execution_effect":"none","status":"accounting_checks_consistent"
        if copied and all(m["status"]=="accounting_checks_consistent" for m in markets) else "review_required",
        "snapshot_started_utc":began,"snapshot_finished_utc":int(time.time()),"copies":copies,
        "window":{"start":start,"split":split,"end_exclusive":end},"markets":markets,
        "candidate_policy_tested":False,"profitability_improvement_validated":False,
        "live_activation_ready":False,
        "limitations":["Per-database read-only backups are individually consistent, not a simultaneous cross-database snapshot.",
          "Baseline trade/capital/position modules cover recent snapshot history; cost and regime/learning use requested cutoffs.",
          "Matching reports establish internal accounting consistency only, not independent broker reconciliation or an improved policy.",
          "Data-quality flags, missing costs, incomplete attribution and genuine prospective comparison require separate review.",
          "No provider requests, broker requests, runtime writes, trading policy changes or service restart. Temporary copies are removed."]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",required=True,type=Path);p.add_argument("--learning-dir",required=True,type=Path)
    p.add_argument("--start",required=True,type=int);p.add_argument("--split",required=True,type=int);p.add_argument("--end",required=True,type=int)
    p.add_argument("--rates-json",type=Path);p.add_argument("--btc-plan",type=Path);p.add_argument("--gold-plan",type=Path)
    a=p.parse_args()
    rates=cost_intelligence.price_schedule(json.loads(a.rates_json.read_text())) if a.rates_json else None
    plans={}
    for s,path in (("BTCUSD",a.btc_plan),("XAUTUSD",a.gold_plan)):
        if path:
            plan=json.loads(path.read_text())
            if plan.get("symbol")!=s:p.error("plan symbol mismatch")
            plans[s]=plan
    print(json.dumps(run(a.data_dir,a.learning_dir,a.start,a.split,a.end,rates,plans),allow_nan=False,indent=2))
if __name__=="__main__":main()
