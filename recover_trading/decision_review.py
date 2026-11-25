"""Read-only decision-to-fill diagnostics. No model or order requests."""
import hashlib,json,sqlite3
from collections import Counter,defaultdict
from contextlib import closing
from pathlib import Path
from statistics import median
from .performance import dec,stamp
from .entry_quotes import attribution

def positive(x):
    n=dec(x)
    return n if n is not None and n>0 else None

def review(decisions,orders,fills,episodes,symbol,entry_quotes=None):
    entry_quotes=entry_quotes or {}
    by_order=defaultdict(list)
    for f in fills:
        by_order[str(f.get("order_id"))].append(f)
    closed=defaultdict(list)
    for e in episodes:
        if e.get("decision_id"):closed[e["decision_id"]].append(e)
    rows=[]; failures=Counter();states=Counter(); telemetry=defaultdict(list)
    for d in decisions:
        result=d.get("result") or {};context=d.get("context") or {}
        action=result.get("action");ident=d["id"]
        row={"id":ident,"created":d["created"],"model":d["model"],"status":d["status"],
             "action":action,"direction":(context.get("direction_engine") or {}).get("direction"),
             "rules":sorted({s["id"] for s in context.get("new_signals",[])}),
             "reason":result.get("reason"),"entry_deviation_bps":None,
             "planned_stop_bps":None,"planned_target_bps":None,"planned_reward_risk":None,
             "fill_stop_bps":None,"fill_target_bps":None,"filled_contracts":None,
             "net_before_funding":None,"outcome":"not_evaluated","order_status":None}
        diag=result.get("diagnostics")
        if isinstance(diag,dict):
            sample={k:diag[k] for k in ("elapsed_ms","headers_ms","request_bytes","response_bytes") if type(diag.get(k)) is int and diag[k]>=0}
            if sample:
                telemetry[d["status"]].append(sample)
                row["provider_metrics"]=sample
        if d["status"]=="failed":
            code=result.get("response_error") or result.get("error") or "unknown"
            failures[code]+=1;row["failure"]=code;row["outcome"]="decision_failed"
        elif d["status"]!="proposed":row["outcome"]="decision_pending_or_unknown"
        elif action=="no_trade":row["outcome"]="no_trade"
        elif action=="trade":
            sign=1 if result.get("side")=="buy" else -1 if result.get("side")=="sell" else None
            en,sl,tp=(positive(result.get(k)) for k in ("entry_reference","stop_loss","take_profit"))
            if sign and all(v is not None for v in (en,sl,tp)):
                stop=sign*(en-sl)/en*10000;target=sign*(tp-en)/en*10000
                row.update(planned_stop_bps=float(stop),planned_target_bps=float(target),
                    planned_reward_risk=float(target/stop) if stop>0 and target>0 else None,
                    bracket_orientation_valid=stop>0 and target>0)
            client=hashlib.sha256(("recover:"+ident).encode()).hexdigest()[:32]
            order=orders.get(client)
            row["outcome"]="no_order_recorded"
            if order:
                row["order_status"]=order["status"];row["outcome"]="submission_"+order["status"]
                if client in entry_quotes:row["entry_quote_evidence"]=entry_quotes[client]
                receipt=order.get("detail") or {};spec=(context.get("demo_account") or {}).get("product") or {}
                oid=receipt.get("id")
                if (order["status"]=="acknowledged" and oid is not None and receipt.get("client_order_id")==client
                    and spec.get("id") is not None and spec.get("symbol")==symbol and str(receipt.get("product_id"))==str(spec["id"])
                    and receipt.get("side")==result.get("side")):
                    candidates=by_order.get(str(oid),[])
                    valid=[f for f in candidates if str(f.get("product_id"))==str(spec["id"]) and f.get("side")==result.get("side")
                           and positive(f.get("size")) is not None and positive(f.get("price")) is not None and stamp(f) is not None]
                    if valid and len(valid)==len(candidates):
                        qty=sum(positive(f["size"]) for f in valid)
                        avg=sum(positive(f["size"])*positive(f["price"]) for f in valid)/qty
                        row.update(filled_contracts=str(qty),average_fill_price=str(avg),outcome="fill_observed_closure_unattributed")
                        if sign and all(v is not None for v in (en,sl,tp)):
                            row.update(entry_deviation_bps=float(sign*(avg/en-1)*10000),
                                       fill_stop_bps=float(sign*(avg-sl)/avg*10000),
                                       fill_target_bps=float(sign*(tp-avg)/avg*10000))
                        row["entry_attribution"]=attribution(entry_quotes.get(client),avg)
                        if len(closed[ident])==1:
                            row.update(outcome="closed_reconciled",net_before_funding=closed[ident][0]["net_before_funding"])
                    elif candidates:row["outcome"]="fill_identity_unverified"
                    else:row["outcome"]="acknowledged_no_fill_evidence"
        states[row["outcome"]]+=1;rows.append(row)
    metrics={}
    for status, samples in telemetry.items():
        metrics[status]={}
        for field in ("elapsed_ms","headers_ms","request_bytes","response_bytes"):
            values=[x[field] for x in samples if field in x]
            if values:
                metrics[status][field]={"samples":len(values),"median":median(values),"maximum":max(values)}
    return {"provider_telemetry":metrics,"version":"decision-review-v1","symbol":symbol,"status":"observed",
            "decision_count":len(rows),"outcome_counts":dict(states),"failure_counts":dict(failures),
            "entry_deviation_samples":sum(r["entry_deviation_bps"] is not None for r in rows),
            "recent":rows[-100:],"limitations":["Positive signed entry deviation means worse fill than AI reference, not measured market slippage.",
             "Unknown submission is not a rejected or losing trade; original broker errors may lack detailed codes.",
             "SL/TP distances refer to the AI plan, not verified exchange trigger coverage.",
             "Closed outcomes only from reconciled attributed episodes; funding excluded.",
             "Reasons are recorded model explanations, not verified causal reasoning. No alternative AI model comparison."]}

def read_review(root,symbol,performance):
    root=Path(root)
    def connect(name):
        return sqlite3.connect((root/name).resolve().as_uri()+"?mode=ro",uri=True,timeout=2)
    try:
        with closing(connect("decisions.sqlite")) as db:
            decisions=[{"id":i,"model":m,"status":s,"created":t,"context":json.loads(c),"result":json.loads(r or "{}")}
                       for i,m,s,t,c,r in db.execute("SELECT id,model,status,created,context,result FROM decisions WHERE symbol=? ORDER BY created,rowid",(symbol,))]
        with closing(connect("orders.sqlite")) as db:
            db.execute("BEGIN")
            orders={i:{"status":s,"detail":json.loads(r or "{}")} for i,s,r in db.execute("SELECT client_id,status,detail FROM orders WHERE symbol=?",(symbol,))}
            fills=[json.loads(r) for r, in db.execute("SELECT detail FROM observed_fills WHERE symbol=?",(symbol,))]
            evidence={}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='entry_quotes'").fetchone():
                evidence={i:json.loads(r) for i,r in db.execute("SELECT client_id,detail FROM entry_quotes WHERE symbol=?",(symbol,))}
        return review(decisions,orders,fills,performance.get("recent_episodes",[]),symbol,evidence)
    except (sqlite3.Error,ValueError,KeyError,TypeError,AttributeError,ArithmeticError):
        return {"status":"unavailable_or_invalid_journal","symbol":symbol}
