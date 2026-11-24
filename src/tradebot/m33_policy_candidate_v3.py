"""Synthetic persistent policy candidate. No broker transport, admission or release API."""
from fractions import Fraction
from datetime import datetime,timezone,timedelta
from pathlib import Path
from contextlib import closing
import json,sqlite3,os
from tradebot.m25_equity_policy_research_v3 import equity_value,loss_text
from tradebot.portfolio_equity_guard import DEFAULT_LIMITS,ANCHOR_WINDOW,stamp
from tradebot.opportunity_journal_v3 import canonical,digest

LIMITS=tuple(Fraction(str(x)) for x in DEFAULT_LIMITS)

def replay(symbol,identity,events):
    if symbol not in ("BTCUSD","XAUTUSD") or not isinstance(identity,str) or not identity.startswith("synthetic-"):
        raise ValueError("fixture_scope")
    if not 1<=len(events)<=20000:raise ValueError("event_budget")
    prior=None;eq=None;index=peak=Fraction(1);day=week=None
    daily=weekly=None;latched=set();uncertainty=set();ids=set();worst=Fraction(0)
    def assess():
        nonlocal peak,worst
        peak=max(peak,index)
        decline=1-index/peak;worst=max(worst,decline)
        if decline>=LIMITS[2]:latched.add("sampled_drawdown")
        if daily is not None and 1-index/daily>=LIMITS[0]:latched.add("daily")
        if weekly is not None and 1-index/weekly>=LIMITS[1]:latched.add("weekly")
    for e in events:
        if e["symbol"]!=symbol or e["fixture_account"]!=identity:raise ValueError("identity")
        t=e["at_us"];key=e["event_id"];kind=e["kind"]
        if type(t) is not int or not 0<t<253402300799000000 or (prior is not None and t<=prior):raise ValueError("time_order")
        if not isinstance(key,str) or not key or len(key)>128 or key in ids:raise ValueError("event_id")
        ids.add(key)
        if prior is not None and t-prior>180000000:uncertainty.add("observation_gap")
        prior=t
        now=datetime.fromtimestamp(t/1000000,timezone.utc)
        d=now.replace(hour=0,minute=0,second=0,microsecond=0);w=d-timedelta(days=d.weekday())
        if day!=d:day=d;daily=None
        if week!=w:week=w;weekly=None
        if kind=="capital":
            if eq is None:uncertainty.add("missing_prior_valuation");continue
            try:
                before=equity_value(e["before"]);after=equity_value(e["after"])
                if before==after or after-before!=Fraction(str(e["flow"])):raise ValueError("unmatched")
            except (KeyError,ValueError,ArithmeticError,TypeError):
                uncertainty.add("unmatched_capital");continue
            if uncertainty:continue
            index*=before/eq;eq=after
        elif kind=="valuation":
            try:v=equity_value(e["equity"])
            except (KeyError,ValueError,ArithmeticError,TypeError):
                uncertainty.add("invalid_valuation");continue
            if uncertainty:continue
            if eq is not None:index*=v/eq
            eq=v
            if daily is None and stamp(day)<=t<stamp(day)+ANCHOR_WINDOW*1000000:daily=index
            if weekly is None and stamp(week)<=t<stamp(week)+ANCHOR_WINDOW*1000000:weekly=index
        else:
            uncertainty.add("unknown_event");continue
        if max(index.numerator.bit_length(),index.denominator.bit_length())>16384:raise ValueError("precision_budget")
        assess()
    return dict(mode="synthetic_persistent_policy_candidate",event_count=len(events),
        status="continuity_unresolved" if uncertainty or daily is None or weekly is None else "fixture_evaluated",
        uncertainty=sorted(uncertainty),observed_breach_history=sorted(latched),
        last_known_index=loss_text(index) if eq is not None else None,
        last_known_max_sampled_decline=loss_text(worst) if eq is not None else None,
        daily_opening_observed=daily is not None,weekly_opening_observed=weekly is not None,
        historical_loss_reconciled=False,broker_evidence_verified=False,
        execution_authorized=False,policy_deployed=False)

def append(path,symbol,identity,event):
    """Fixture-only immutable journal; recompute history on every append/restart."""
    if not isinstance(identity,str) or not identity.startswith("synthetic-"):
        raise ValueError("fixture_only")
    p=Path(path)
    if not p.name.startswith("synthetic-"):raise ValueError("fixture_path_required")
    if len(canonical(event))>8192:raise ValueError("event_size")
    fd=os.open(p,os.O_CREAT|os.O_NOFOLLOW|os.O_RDWR,0o600)
    try:
        st=os.fstat(fd)
        if st.st_uid!=os.geteuid() or st.st_mode&0o077 or st.st_nlink!=1:raise ValueError("private_fixture")
    finally:os.close(fd)
    with closing(sqlite3.connect(p,timeout=5)) as db,db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE IF NOT EXISTS fixture_events(seq INTEGER PRIMARY KEY,body TEXT NOT NULL,sha TEXT NOT NULL)")
        for op in ("UPDATE","DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{op.lower()} BEFORE {op} ON fixture_events BEGIN SELECT RAISE(ABORT,'immutable fixture'); END")
        db.execute("BEGIN IMMEDIATE")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        events=[]
        for i,raw,h in db.execute("SELECT seq,body,sha FROM fixture_events ORDER BY seq LIMIT 20001"):
            e=json.loads(raw)
            if i!=len(events)+1 or digest(e)!=h:raise ValueError("journal_integrity")
            events.append(e)
        if events and event==events[-1]:return replay(symbol,identity,events)
        result=replay(symbol,identity,events+[event])
        db.execute("INSERT INTO fixture_events VALUES(?,?,?)",(len(events)+1,canonical(event),digest(event)))
        return result
