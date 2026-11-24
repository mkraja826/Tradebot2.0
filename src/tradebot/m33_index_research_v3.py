"""Prospective conditional index research; never a production risk or release decision."""
from fractions import Fraction
from pathlib import Path
from datetime import datetime,timezone
from contextlib import closing
import os,sqlite3,json
from tradebot.m33_coverage_v3 import audit
from tradebot.m25_equity_policy_research_v3 import equity_value,loss_text
from tradebot.opportunity_journal_v3 import canonical,digest
from tradebot.portfolio_equity_guard import stamp
from tradebot.research_collector_v3 import atomic_json

def calculate(coverage,evidence):
    out=dict(status="continuity_unresolved",conditional_index=None,
             observed_peak_decline=None,max_observed_decline=None,
             broker_finality_verified=False,transfer_adjusted_index_verified=False,
             historical_loss_reconciled=False,execution_authorized=False)
    if coverage.get("posting_index_consistent") is not True:return out
    for key in ("uncovered_before_latest_query_us","overlapping_query_late_ids",
                "overlapping_query_missing_ids","conflicting_posting_ids",
                "unclassified_ids","capital_posting_ids","equity_gaps_over_180s"):
        if type(coverage.get(key)) is not int or coverage[key]!=0:return dict(out,reason=key)
    rows=[(t,equity_value(v)) for t,v in evidence["values"] if t<=evidence["through"]]
    if len(rows)<2 or rows[-1][0]!=evidence["through"] or any(b[0]<=a[0] for a,b in zip(rows,rows[1:])):
        return dict(out,reason="sample_scope")
    first=peak=rows[0][1];worst=Fraction(0)
    for _,v in rows:
        peak=max(peak,v);worst=max(worst,1-v/peak)
    index=rows[-1][1]/first
    return dict(out,status="conditional_no_capital_index_observed",sample_count=len(rows),
                first_observed_us=rows[0][0],through_us=rows[-1][0],
                conditional_index=loss_text(index),exact_index_numerator=str(index.numerator),
                exact_index_denominator=str(index.denominator),
                observed_peak_decline=loss_text(1-rows[-1][1]/peak),
                max_observed_decline=loss_text(worst),unsampled_peaks_verified=False)

def record(path,s,binding,observed,result,evidence_digest):
    if s not in ("BTCUSD","XAUTUSD") or len(binding)!=64 or type(observed) is not int or observed<=0:
        raise ValueError("scope")
    if result["execution_authorized"] is not False:raise ValueError("research_only")
    p=Path(path)
    fd=os.open(p,os.O_CREAT|os.O_NOFOLLOW|os.O_RDWR,0o600)
    try:
        st=os.fstat(fd)
        if st.st_uid!=os.geteuid() or st.st_mode&0o077 or st.st_nlink!=1:raise ValueError("private_archive")
    finally:os.close(fd)
    body=dict(symbol=s,binding=binding,observed=observed,result=result,evidence_digest=evidence_digest)
    h=digest(body)
    with closing(sqlite3.connect(p,timeout=5)) as db,db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE IF NOT EXISTS snapshots(symbol TEXT,binding TEXT,observed INTEGER,body TEXT,sha TEXT,PRIMARY KEY(symbol,observed))")
        for op in ("UPDATE","DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{op.lower()} BEFORE {op} ON snapshots BEGIN SELECT RAISE(ABORT,'immutable evidence'); END")
        db.execute("BEGIN IMMEDIATE")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        if db.execute("SELECT 1 FROM snapshots WHERE (symbol=? AND binding<>?) OR (symbol<>? AND binding=?) LIMIT 1",(s,binding,s,binding)).fetchone():raise ValueError("binding")
        last=db.execute("SELECT observed,sha FROM snapshots WHERE symbol=? ORDER BY observed DESC LIMIT 1",(s,)).fetchone()
        if last and observed<=last[0]:
            if observed!=last[0] or h!=last[1]:raise ValueError("nonmonotonic_snapshot")
        else:db.execute("INSERT INTO snapshots VALUES(?,?,?,?,?)",(s,binding,observed,canonical(body),h))
        count=db.execute("SELECT count(*) FROM snapshots WHERE symbol=?",(s,)).fetchone()[0]
    return count

def collect(root,*,clock=lambda:datetime.now(timezone.utc)):
    root=Path(root);now=clock()
    out=dict(mode="conditional_index_research_only",checked_at=int(now.timestamp()),
             markets={},execution_authorized=False,orders_submitted=0,policy_changed=False)
    for s in ("BTCUSD","XAUTUSD"):
        try:
            c,e=audit(root,s,now,include_evidence=True)
            r=calculate(c,e)
            count=record(root/"m33-index-research-v3.sqlite",s,e["binding"],stamp(now),r,digest(e))
            r.update(snapshot_count=count)
        except (OSError,sqlite3.Error,ValueError,KeyError,TypeError,ArithmeticError,AttributeError) as exc:
            r=dict(status="unavailable",reason=type(exc).__name__,execution_authorized=False)
        out["markets"][s]=r
    atomic_json(root/"m33-index-research-v3.json",out)
    return out
