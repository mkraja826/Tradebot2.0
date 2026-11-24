"""Observed prospective declines only. Never evaluates a release or risk limit."""
from datetime import datetime,timezone,timedelta
from contextlib import closing
from pathlib import Path
import json,sqlite3
from tradebot.equity_receipt import validate_receipt
from tradebot.opportunity_journal_v3 import digest
from tradebot.portfolio_equity_guard import stamp,ANCHOR_WINDOW
from tradebot.m25_equity_policy_research_v3 import equity_value,loss_text
from tradebot.m20_subaccount_baseline_v3 import read_private
from tradebot.research_collector_v3 import atomic_json

def calculate(rows,now):
    n=stamp(now)
    if not 2<=len(rows)<=11000:raise ValueError("sample_count")
    times=[t for t,v in rows]
    if any(type(t) is not int or t<=0 for t in times) or any(b<=a for a,b in zip(times,times[1:])) or not 0<=n-times[-1]<=180000000:raise ValueError("time_scope")
    values=[equity_value(v) for t,v in rows]
    day=now.astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    week=day-timedelta(days=day.weekday())
    loss=lambda x:loss_text(max(0,1-values[-1]/x))
    gaps=sum(b-a>180000000 for a,b in zip(times,times[1:]))
    out=dict(status="observed_raw_declines_only",sample_count=len(rows),gaps_over_180s=gaps,
             sampled_archive_peak_decline=loss(max(values)),historical_peak_verified=False,
             intraperiod_peak_verified=False,historical_loss_reconciled=False,
             transfer_adjusted_risk_index_verified=False,execution_authorized=False)
    for name,start in (("daily",day),("weekly",week)):
        a=stamp(start)
        anchor=next((v for t,v in zip(times,values) if a<=t<a+ANCHOR_WINDOW*1000000),None)
        out[name+"_observed_decline"]=loss(anchor) if anchor is not None and not gaps else None
        out[name+"_opening_status"]="observed" if anchor is not None else "unobserved"
    return out

def read_window(path,s,start,end):
    if not path.is_file() or path.is_symlink():raise ValueError("ledger")
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        rows=db.execute("SELECT binding,stamp,body,sha FROM observations WHERE symbol=? AND stamp BETWEEN ? AND ? ORDER BY stamp LIMIT 11001",(s,start,end)).fetchall()
        if not 2<=len(rows)<=11000 or rows[0][1]!=start or rows[-1][1]!=end or len({r[0] for r in rows})!=1:raise ValueError("window_scope")
        result=[]
        for binding,t,raw,h in rows:
            r=json.loads(raw)
            if digest(r)!=h or (r["symbol"],r["account_binding"],r["observed_us"])!=(s,binding,t):raise ValueError("archive_scope")
            validate_receipt(r["equity_usd"],r["receipt"],now=datetime.fromtimestamp(t/1e6,timezone.utc))
            if r["receipt"]["received_us"]!=t:raise ValueError("receipt_time")
            result.append((t,r["equity_usd"]))
        return result

def collect(root,*,clock=lambda:datetime.now(timezone.utc)):
    root=Path(root);now=clock()
    out=dict(mode="prospective_loss_observations_only",markets={},checked_at=int(now.timestamp()),
             execution_authorized=False,orders_submitted=0,policy_changed=False)
    try:
        report=json.loads(read_private(root/"m31-cashflow-evidence-v3.json"))
        if report["mode"]!="prospective_cashflow_evidence_only" or report["execution_authorized"] is not False or not 0<=now.timestamp()-report["checked_at"]<=90:raise ValueError("cashflow_scope")
    except (OSError,ValueError,KeyError,TypeError):report={}
    for s in ("BTCUSD","XAUTUSD"):
        try:
            a=report["markets"][s]
            if a["status"]!="bounded_cashflow_comparison" or a["account_binding_verified"] is not True or a["requested_window_returned"] is not True or a["capital_posting_count"]!=0 or a["unclassified_count"]!=0 or a["boundary_ambiguous"] is not False:
                raise ValueError("cashflow_not_resolved")
            rows=read_window(root/"m31-equity-evidence-v3.sqlite",s,a["window_start_us"],a["window_end_us"])
            r=calculate(rows,now)
        except (OSError,sqlite3.Error,ValueError,KeyError,TypeError,ArithmeticError) as exc:
            r=dict(status="unavailable_or_unresolved",reason=type(exc).__name__,execution_authorized=False)
        out["markets"][s]=r
    atomic_json(root/"m31-loss-observations-v3.json",out)
    return out
