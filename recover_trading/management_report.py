"""Read-only management telemetry; manual evidence is not autonomous execution."""
import json,sqlite3
from contextlib import closing
from pathlib import Path
from collections import Counter
from statistics import median
from .performance import dec
VERSION="management-report-v1"

def read_rows(path,sql,args=()):
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            return db.execute(sql,args).fetchall()
    except sqlite3.Error:return None

def parsed(raw):
    try:
        obj=json.loads(raw or "{}")
        return obj if isinstance(obj,dict) else {}
    except (TypeError,ValueError):return {}

def evidence(root):
    out=[]
    for filename,kind in (("manual_management.sqlite","partial_reduction"),("manual_amendments.sqlite","individual_amendment")):
        rows=read_rows(root/filename,"SELECT id,status,detail FROM attempts") or []
        for ident,status,raw in rows:
            d=parsed(raw)
            if kind=="partial_reduction":
                o=d.get("order") or {};q=dec(d.get("position_size"));legs=d.get("legs") or []
                if status!="partial_close_observed" or d.get("verification")!=status or d.get("orders_complete") is not True or d.get("bracket_state")!="matching_legs_observed" or o.get("reduce_only") is not True or o.get("state")!="closed" or dec(o.get("unfilled_size"))!=0 or q is None or q==0 or len(legs)!=2:continue
                if {l.get("stop_order_type") for l in legs}!={"stop_loss_order","take_profit_order"} or any(dec(l.get("unfilled_size"))!=abs(q) or l.get("reduce_only") is not True for l in legs):continue
                out.append({"kind":kind,"status":"recorded_exchange_verified","order_id":o.get("id"),"remaining_contracts":str(abs(q))})
            else:
                if status=="matching_target_and_unchanged_stop_observed":
                    v=d.get("verification") or {};p=d.get("plan") or {};before=p.get("before") or {};o=d.get("receipt") or {}
                    legs=v.get("legs") or [];positions=v.get("positions") or [];q=dec(before.get("position_size"))
                    if d.get("response")!="acknowledged" or v.get("status")!=status or q is None or not q or len(positions)!=1 or dec(positions[0].get("size"))!=q or dec(positions[0].get("entry_price"))!=dec(before.get("entry_price")) or len(legs)!=2:continue
                    by={l.get("stop_order_type"):l for l in legs};a=by.get("stop_loss_order",{});b=by.get("take_profit_order",{})
                    if a.get("id")!=before.get("stop_order_id") or b.get("id")!=before.get("target_order_id") or o.get("id")!=b.get("id") or dec(a.get("stop_price"))!=dec(before.get("stop_price")) or dec(b.get("stop_price"))!=dec(p.get("desired_target")) or dec(o.get("stop_price"))!=dec(p.get("desired_target")):continue
                    if any(l.get("reduce_only") is not True or l.get("stop_trigger_method")!="mark_price" or dec(l.get("unfilled_size"))!=abs(q) for l in legs):continue
                    out.append({"kind":"take_profit_order_amendment","status":"recorded_exchange_verified","order_id":o["id"],"trigger":str(o["stop_price"])})
                    continue
                o=d.get("result") or {};v=d.get("observed") or {};legs=v.get("legs") or []
                q=dec(v.get("position_size"))
                if status!="matching_triggers_observed" or d.get("response")!="acknowledged" or v.get("verification")!=status or v.get("bracket_state")!="matching_legs_observed" or q is None or not q or len(legs)!=2:continue
                matched=[l for l in legs if l.get("id")==o.get("id") and dec(l.get("stop_price"))==dec(o.get("stop_price")) and l.get("reduce_only") is True and dec(l.get("unfilled_size"))==abs(q)]
                if len(matched)!=1:continue
                leg=matched[0].get("stop_order_type")
                if leg not in ("stop_loss_order","take_profit_order"):continue
                out.append({"kind":leg+"_amendment","status":"recorded_exchange_verified","order_id":o.get("id"),"trigger":str(o.get("stop_price"))})
    return out

def report(root,symbol,heartbeat):
    root=Path(root)
    rows=read_rows(root/"orders.sqlite","SELECT created,status,result FROM management_shadow WHERE symbol=? ORDER BY created DESC",(symbol,))
    attempts=read_rows(root/"orders.sqlite","SELECT action,status,count(*) FROM management_attempts WHERE symbol=? GROUP BY action,status",(symbol,))
    mode=(heartbeat or {}).get("management_execution") or {}
    out={"version":VERSION,"execution_effect":"none","status":"observed" if rows is not None and attempts is not None else "incomplete_journal","enabled":mode.get("enabled"),"runtime_status":mode.get("status"),"manual_exchange_evidence":evidence(root),"evaluations":{},"actions":{},"errors":{},"latency_samples":0,"median_response_ms":None,"latest":None,"autonomous_attempts":[{"action":a,"status":s,"count":n} for a,s,n in attempts or []]}
    counts=Counter();actions=Counter();errors=Counter();times=[]
    for created,status,raw in rows or []:
        d=parsed(raw);counts[status]+=1
        action=(d.get("proposal") or {}).get("action")
        if status=="proposed" and action:actions[action]+=1
        if status=="failed":errors[d.get("response_error") or d.get("error") or "unknown"]+=1
        diag=d.get("diagnostics") or {};ms=diag.get("elapsed_ms")
        if status in ("proposed","failed") and type(ms) is int and ms>=0:times.append(ms)
        if out["latest"] is None and status in ("proposed","failed","requested"):
            out["latest"]={"created":created,"status":status,"action":action,"error":d.get("response_error") or d.get("error")}
    out.update(evaluations=dict(counts),actions=dict(actions),errors=dict(errors),latency_samples=len(times),median_response_ms=median(times) if times else None)
    return out
