"""Experience projection from existing reconciliation ledger and synthetic replay.
No ledger creation, broker writes, provider calls, or strategy control.
"""
from pathlib import Path
from contextlib import closing
from collections import Counter,defaultdict
from decimal import Decimal
import json,sqlite3
from tradebot.opportunity_journal_v3 import digest,ROUTE,known_route
from tradebot.ai_decision_v3 import validate
from tradebot.fire_performance import _validated,_decimal,_stats
from tradebot.market_data_v3 import MARKETS

def read_ledger(path,symbol,*,now_us):
    p=Path(path)
    if not p.exists(): return {"status":"ledger_missing","records":[],"unverified":None}
    if not p.is_file() or p.is_symlink(): raise ValueError("untrusted_ledger")
    with closing(sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True)) as db:
        db.execute("PRAGMA query_only=ON"); db.execute("BEGIN")
        grouped=defaultdict(list)
        for key,raw in db.execute("SELECT trade_key,body FROM reports"):
            if key.startswith(symbol+":"): grouped[key].append(json.loads(raw))
        verified=[]; unknown=0
        for key,reports in grouped.items():
            stamps=[r.get("reconciliation_as_of_us") for r in reports]
            if any(type(t) is not int or not 0<t<=now_us for t in stamps): unknown+=1; continue
            latest=[r for r in reports if r["reconciliation_as_of_us"]==max(stamps)]
            if len({digest(r) for r in latest})!=1: unknown+=1; continue
            r=latest[0]; v=_validated(r,key,max(stamps))
            if v is None: unknown+=1; continue
            if any(db.execute("SELECT trade_key FROM claims WHERE kind=? AND id=?",(kind,i)).fetchone()!=(key,) for kind,ids in (("fill",v["fill_ids"]),("posting",v["posting_ids"])) for i in ids):
                unknown+=1; continue
            try:
                entry=_decimal(r["reconciled_entry_price"]); exit=_decimal(r["reconciled_exit_price"]); qty=_decimal(r["filled_contracts"])
                if min(entry,exit,qty)<=0: raise ValueError("invalid_fill_summary")
            except (ValueError,KeyError): unknown+=1; continue
            verified.append({"trade_key":key,"as_of_us":max(stamps),"entry_at_us":r["entry_at_us"],"exit_at_us":r["exit_at_us"],
                "holding_seconds":(r["exit_at_us"]-r["entry_at_us"])/1e6,"entry_price":str(entry),"exit_price":str(exit),"contracts":str(qty),
                "net_usd":str(v["pnl"]),"fees_usd":str(_decimal(r["reconciled_fees_usd"])),"funding_usd":str(_decimal(r["funding_cashflow_usd"])),
                "evidence_sha256":digest(r),"source":"historical_reconciliation_ledger","entry_efficiency":None,"exit_efficiency":None})
    return {"status":"historical_only","records":verified,"unverified":unknown}

def replay_scorecards(path):
    """Synthetic validation coverage, not model quality or model performance."""
    out={s:{"records":0,"valid":0,"invalid":0,"actions":{},"model":ROUTE[s],"source":"synthetic_replay","model_quality":None} for s in MARKETS}
    if not Path(path).is_file(): return out
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)) as db:
        for event,s,h,raw in db.execute("SELECT event_id,symbol,request_hash,payload FROM replays"):
            if s not in out: continue
            x=out[s]; x["records"]+=1
            try:
                r=json.loads(raw); q=r["request"]; a=r["response"]
                if r["mode"]!="synthetic_replay" or r["execution_authorized"] is not False or r["paid_ai_requests"]!=0 or r["orders_submitted"]!=0: raise ValueError()
                if h!=q["request_sha256"] or h!=digest(q["payload"]) or digest(a)!=r["response_sha256"] or q["payload"]["event_id"]!=event or q["payload"]["symbol"]!=s or not known_route(s,q["model_if_enabled"]): raise ValueError()
                validate(a,q)
                x["valid"]+=1; x["actions"][a["action"]]=x["actions"].get(a["action"],0)+1
            except (ValueError,TypeError,KeyError): x["invalid"]+=1
    return out

def report(root,legacy_root,*,now_us):
    from tradebot.research_collector_v3 import atomic_json
    root=Path(root); legacy_root=Path(legacy_root)
    scores=replay_scorecards(root/"ai-replay-v3.sqlite")
    result={"mode":"read_only_experience","checked_at_us":now_us,"markets":{},"scanner_control":False,"orders_submitted":0,"ai_requests":0}
    for s,label in (("BTCUSD","btc-isolated"),("XAUTUSD","gold-isolated")):
        try: history=read_ledger(legacy_root/label/"fire-reconciliation.sqlite",s,now_us=now_us)
        except (ValueError,sqlite3.Error,TypeError,KeyError): history={"status":"unavailable","records":[],"unverified":None}
        rows=history["records"]
        stats=_stats([{"key":r["trade_key"],"exit_at_us":r["exit_at_us"],"pnl":Decimal(r["net_usd"])} for r in rows])
        result["markets"][s]={"historical_evidence_status":history["status"],"unverified_trades":history["unverified"],
            "historical_verified_subset":stats,"experience_records":rows,"synthetic_scorecard":scores[s],
            "entry_exit_efficiency_status":"requires_matched_decision_and_market_path",
            "warning":"Historical local reports only; not current account P&L. Synthetic scorecards are not model accuracy."}
    atomic_json(root/"experience-status-v3.json",result)
    return result
