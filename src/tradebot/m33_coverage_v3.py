"""Audit recorded query coverage, not broker finality or risk authorization."""
from contextlib import closing
from pathlib import Path
from datetime import datetime,timezone
import json,sqlite3
from tradebot.opportunity_journal_v3 import digest
from tradebot.m33_cashflow_archive_v3 import DAY
from tradebot.m20_subaccount_equity_v3 import CAPITAL_TYPES
from tradebot.isolated_performance import POSTED_TYPES
from tradebot.equity_receipt import validate_receipt
from tradebot.portfolio_equity_guard import stamp
from tradebot.research_collector_v3 import atomic_json

def audit_windows(windows,start,end):
    if not windows or not 0<start<end:raise ValueError("missing_window")
    intervals=[];versions={};late=set();missing=set();unknown=set();capital=set();active=[]
    last=0;prior_start=0;prior_end=0
    for w in windows:
        a,b,t=w["start"],w["end"],w["observed"]
        if not 0<a<b<=t or t<=last or b-a>DAY:raise ValueError("window_order")
        if a<prior_start or b<prior_end:raise ValueError("regressing_query_window")
        last=t;prior_start=a;prior_end=b;intervals.append((a,b))
        rows={r["id"]:r for r in w["postings"]}
        if len(rows)!=len(w["postings"]):raise ValueError("duplicate_posting")
        for k,r in rows.items():
            if not a<=r["at_us"]<=b:raise ValueError("posting_scope")
            versions.setdefault(k,set()).add(digest(r))
            if r["asset"]!="USD" or r["product_id"] not in (None,str(w["product_id"])) or r["type"] not in CAPITAL_TYPES|POSTED_TYPES:unknown.add(k)
            if r["type"] in CAPITAL_TYPES:capital.add(k)
        active=[(x,y,z) for x,y,z in active if y>=a]
        if len(active)>256:raise ValueError("overlap_budget")
        for x,y,z in active:
            lo,hi=max(a,x),min(b,y)
            # Exclude query boundary timestamps: endpoint inclusion is unproven.
            if lo>=hi:continue
            before={k for k,r in z.items() if lo<r["at_us"]<hi}
            after={k for k,r in rows.items() if lo<r["at_us"]<hi}
            late.update(after-before);missing.update(before-after)
        active.append((a,b,rows))
    cursor=start;gap=0;gaps=0
    for a,b in sorted(intervals):
        if b<=cursor or a>=end:continue
        if a>cursor:gap+=a-cursor;gaps+=1
        cursor=max(cursor,min(b,end))
    if cursor<end:gap+=end-cursor;gaps+=1
    return dict(query_windows=len(windows),uncovered_us=gap,coverage_gaps=gaps,
        overlapping_query_late_ids=len(late),overlapping_query_missing_ids=len(missing),
        conflicting_posting_ids=sum(len(v)>1 for v in versions.values()),
        unclassified_ids=len(unknown),capital_posting_ids=len(capital),
        query_intervals_cover_samples=gap==0,broker_finality_verified=False,
        historical_loss_reconciled=False,execution_authorized=False)

def snapshot(path,query,args,limit):
    if not path.is_file() or path.is_symlink():raise ValueError("archive_missing")
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        rows=db.execute(query+" LIMIT ?",(*args,limit+1)).fetchall()
        if not rows or len(rows)>limit:raise ValueError("archive_budget")
        return rows

def audit(root,s,now,*,include_evidence=False):
    root=Path(root);n=stamp(now)
    eq=snapshot(root/"m31-equity-evidence-v3.sqlite",
        "SELECT binding,stamp,body,sha FROM observations WHERE symbol=? ORDER BY stamp",(s,),20000)
    binding=eq[0][0];times=[];values=[]
    for b,t,raw,h in eq:
        r=json.loads(raw)
        if b!=binding or (r["symbol"],r["account_binding"],r["observed_us"])!=(s,b,t) or digest(r)!=h or r["receipt"]["received_us"]!=t or t>n:
            raise ValueError("equity_scope")
        validate_receipt(r["equity_usd"],r["receipt"],now=datetime.fromtimestamp(t/1e6,timezone.utc))
        times.append(t)
        values.append((t,r["equity_usd"]))
    if len(times)<2 or any(a>=b for a,b in zip(times,times[1:])):raise ValueError("equity_order")
    path=root/"m33-cashflow-archive-v3.sqlite"
    if not path.is_file() or path.is_symlink():raise ValueError("archive_missing")
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        records=db.execute("SELECT binding,observed,start,end,body,sha FROM windows WHERE symbol=? ORDER BY observed LIMIT 2001",(s,)).fetchall()
        if not 1<=len(records)<=2000:raise ValueError("query_budget")
        windows=[];expected=set();pid=None
        for b,t,a,z,raw,h in records:
            w=json.loads(raw)
            if b!=binding or (w["symbol"],w["binding"],w["observed"],w["start"],w["end"])!=(s,b,t,a,z) or digest(w)!=h or t>n or a<times[0] or z>times[-1]:
                raise ValueError("query_scope")
            if type(w["product_id"]) is not int or w["product_id"]<=0 or (pid is not None and pid!=w["product_id"]):raise ValueError("product_scope")
            pid=w["product_id"]
            windows.append(w)
            for r in w["postings"]:expected.add((r["id"],digest(r)))
        actual=set()
        for b,k,h,raw in db.execute("SELECT binding,id,sha,body FROM posting_versions WHERE symbol=?",(s,)):
            r=json.loads(raw)
            if b!=binding or r["id"]!=k or digest(r)!=h:raise ValueError("posting_index")
            actual.add((k,h))
            if len(actual)>len(expected):raise ValueError("posting_index")
        if actual!=expected:raise ValueError("posting_index")
    out=audit_windows(windows,times[0],times[-1])
    through=max(w["end"] for w in windows)
    settled=audit_windows(windows,times[0],through)
    out.update(status="archive_coverage_observed",equity_samples=len(times),
               equity_gaps_over_180s=sum(b-a>180000000 for a,b in zip(times,times[1:])),
               latest_equity_age_seconds=round((n-times[-1])/1e6,3),
               uncovered_before_latest_query_us=settled["uncovered_us"],
               trailing_query_lag_us=times[-1]-through,posting_index_consistent=True,
               exact_transfer_valuations_verified=False)
    if include_evidence:
        return out,dict(binding=binding,values=values,through=through,query_digest=digest(windows))
    return out

def collect(root,*,clock=lambda:datetime.now(timezone.utc)):
    root=Path(root);now=clock()
    out=dict(mode="cashflow_archive_coverage_only",checked_at=int(now.timestamp()),
             markets={},execution_authorized=False,orders_submitted=0,policy_changed=False)
    for s in ("BTCUSD","XAUTUSD"):
        try:r=audit(root,s,now)
        except (OSError,sqlite3.Error,ValueError,KeyError,TypeError,ArithmeticError,AttributeError) as e:
            r=dict(status="unavailable",reason=type(e).__name__,execution_authorized=False)
        out["markets"][s]=r
    atomic_json(root/"m33-coverage-v3.json",out)
    return out
