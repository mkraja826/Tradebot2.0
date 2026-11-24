"""Read-only period coverage; no risk anchor or release authority."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from contextlib import closing
import sqlite3,json
from tradebot.equity_receipt import validate_receipt
from tradebot.portfolio_equity_guard import stamp,ANCHOR_WINDOW
from tradebot.m20_subaccount_baseline_v3 import read_private
from tradebot.research_collector_v3 import atomic_json

def period(start,now,first,created,times):
    end=start+ANCHOR_WINDOW*1000000
    if not 0<created<=first<=now or start>now:raise ValueError("invalid_period")
    seen=any(start<=t<end and created<=t<=now for t in times)
    if seen:state="receipt_observed_in_window"
    elif created>=end:state="account_created_after_window"
    elif now<end:state="window_pending"
    elif first>=end:state="opening_unobserved"
    else:state="opening_receipt_missing"
    return dict(state=state,opening_receipt_present=seen,
                historical_account_binding_verified=False,risk_anchor_created=False)

def audit(path,creation,now):
    if not path.is_file() or path.is_symlink():raise ValueError("ledger_unavailable")
    n=stamp(now);c=stamp(creation)
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        rows=db.execute("SELECT e.observed_us,e.equity_usd,e.origin,r.receipt FROM equity_evidence e LEFT JOIN equity_read_receipts r ON e.observed_us=r.observed_us ORDER BY e.observed_us LIMIT 20001").fetchall()
        if not 1<=len(rows)<=20000:raise ValueError("coverage_outside_audit_bound")
        times=[]
        for t,e,origin,receipt in rows:
            if not c<=t<=n or origin!="delta_demo_signed_wallet" or not receipt:raise ValueError("invalid_observation")
            if stamp(validate_receipt(e,json.loads(receipt),now=datetime.fromtimestamp(t/1e6,timezone.utc)))!=t:raise ValueError("receipt_mismatch")
            times.append(t)
    day=now.astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    week=day-timedelta(days=day.weekday())
    gaps=[b-a for a,b in zip(times,times[1:])]
    return dict(status="receipt_coverage_audited",observation_count=len(times),
        unobserved_since_creation_seconds=(times[0]-c)/1e6,
        latest_observation_age_seconds=(n-times[-1])/1e6,
        max_sample_gap_seconds=max(gaps,default=0)/1e6,
        sample_gaps_over_180s=sum(g>180000000 for g in gaps),
        daily=period(stamp(day),n,times[0],c,times),
        weekly=period(stamp(week),n,times[0],c,times),
        historical_account_binding_verified=False,inception_equity_verified=False,risk_anchor_created=False)

def collect(root,*,legacy_root=Path("/home/support/Tradebot2.0/data")):
    root=Path(root);now=datetime.now(timezone.utc)
    source=json.loads(read_private(root/"m25-inception-evidence-v3.json"))
    if source["mode"]!="independent_inception_evidence_only" or source["execution_authorized"] is not False:raise ValueError("source_scope")
    out=dict(mode="historical_period_coverage_only",checked_at=int(now.timestamp()),markets={},
             execution_authorized=False,orders_submitted=0,policy_changed=False)
    for s,d in (("BTCUSD","btc-isolated"),("XAUTUSD","gold-isolated")):
        try:
            a=source["markets"][s]
            if a["creation_timestamp_verified"] is not True:raise ValueError("creation_unverified")
            r=audit(legacy_root/d/"fire-equity-risk.sqlite",datetime.fromisoformat(a["roster_creation_at"]),now)
        except Exception as exc:r=dict(status="unavailable",reason=type(exc).__name__)
        out["markets"][s]=r
    atomic_json(root/"m27-period-evidence-v3.json",out)
    return out
