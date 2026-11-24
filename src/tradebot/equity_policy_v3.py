"""Separate-account equity research, synthetic input only. No admission API."""
from fractions import Fraction
from tradebot.m25_equity_policy_research_v3 import study,equity_value,loss_text

MARKETS=('BTCUSD','XAUTUSD')

def account_research(fixture):
    result=study(fixture)
    result['maximum_observed_drawdown']=None
    if result['status']!='fixture_calculated':return result
    index=peak=Fraction(1);worst=Fraction(0);previous=None
    for event in fixture['events']:
        if event['kind']=='valuation':
            current=equity_value(event['equity'])
            if previous is not None:index*=current/previous
        else:
            index*=equity_value(event['before'])/previous
            current=equity_value(event['after'])
        peak=max(peak,index)
        worst=max(worst,1-index/peak)
        previous=current
    result['maximum_observed_drawdown']=loss_text(worst)
    return result

def compare_accounts(fixtures):
    """Compare two independently scoped synthetic histories, never pool equity."""
    if not isinstance(fixtures,dict) or set(fixtures)!=set(MARKETS):
        raise ValueError('exactly_two_research_markets_required')
    identities=set();markets={}
    for symbol in MARKETS:
        f=fixtures[symbol]
        if f.get('symbol')!=symbol:raise ValueError('market_mismatch')
        identity=f.get('fixture_account')
        if not isinstance(identity,str) or not identity or identity in identities:
            raise ValueError('distinct_fixture_accounts_required')
        identities.add(identity)
        markets[symbol]=account_research(f)
    return dict(mode='independent_equity_research_only',markets=markets,
                historical_equivalence_verified=False,policy_deployed=False,
                execution_authorized=False,orders_submitted=0)


def _historical_rows(path,now):
    import json,sqlite3
    from contextlib import closing
    from datetime import datetime,timezone
    from tradebot.equity_receipt import validate_receipt
    if path.is_symlink() or not path.is_file():raise ValueError('historical_archive_missing')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise ValueError('historical_integrity')
        rows=db.execute('SELECT e.observed_us,e.equity_usd,r.receipt FROM equity_evidence e LEFT JOIN equity_read_receipts r ON e.observed_us=r.observed_us WHERE e.observed_us<=? ORDER BY e.observed_us LIMIT 20001',(int(now.timestamp()*1e6),)).fetchall()
    if not 2<=len(rows)<=20000:raise ValueError('historical_budget')
    for t,v,raw in rows:
        receipt=json.loads(raw);validate_receipt(v,receipt,now=datetime.fromtimestamp(t/1e6,timezone.utc))
        if receipt['received_us']!=t:raise ValueError('historical_time')
    return rows


def refresh_account_state(root,legacy_root,*,now=None):
    """Consolidate archived broker evidence without granting execution authority."""
    from pathlib import Path
    from datetime import datetime,timezone
    from tradebot.m33_coverage_v3 import audit
    from tradebot.m33_index_research_v3 import calculate
    from tradebot.m38_equity_report_v3 import metrics
    now=now or datetime.now(timezone.utc);root=Path(root);legacy_root=Path(legacy_root)
    prepared={};bindings=set()
    for s,d in zip(MARKETS,('btc-isolated','gold-isolated')):
        rows=_historical_rows(legacy_root/d/'fire-equity-risk.sqlite',now)
        historical=metrics([(t,v) for t,v,_ in rows])
        coverage,evidence=audit(root,s,now,include_evidence=True)
        binding=evidence['binding']
        if binding in bindings:raise ValueError('duplicate_account_binding')
        bindings.add(binding);index=calculate(coverage,evidence)
        historical.update(historical_binding_verified=False,capital_adjustment_verified=False)
        risk=_evaluate_archives(rows,coverage,evidence,index,now)
        risk["reconciliation"]=_reconciliation_state(root,s,now)
        prepared[s]=(rows,evidence['values'],dict(symbol=s,binding=binding,historical_raw=historical,prospective_index=index,coverage=coverage,risk_evaluation=risk,execution_authorized=False,policy_deployed=False))
    _persist_account_state(root/'v3-equity-state.sqlite',prepared)
    return dict(mode='native_equity_state_only',markets={s:{k:v for k,v in data[2].items() if k not in ('binding','historical_digest','prospective_digest')} for s,data in prepared.items()},execution_authorized=False,policy_deployed=False,historical_equivalence_verified=False)


def _persist_account_state(path,prepared):
    import json,os,sqlite3
    from contextlib import closing
    from tradebot.opportunity_journal_v3 import canonical,digest
    fd=os.open(path,os.O_CREAT|os.O_NOFOLLOW|os.O_RDWR,0o600)
    try:
        st=os.fstat(fd)
        if st.st_uid!=os.geteuid() or st.st_mode&0o077 or st.st_nlink!=1:raise ValueError('private_state_required')
    finally:os.close(fd)
    with closing(sqlite3.connect(path,timeout=5)) as db,db:
        db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS state_history(seq INTEGER PRIMARY KEY,symbol TEXT NOT NULL,body TEXT NOT NULL,sha TEXT NOT NULL)')
        for op in ('UPDATE','DELETE'):db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{op.lower()} BEFORE {op} ON state_history BEGIN SELECT RAISE(ABORT,'immutable state'); END")
        if db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise ValueError('state_integrity')
        prior={}
        for i,(seq,s,raw,h) in enumerate(db.execute('SELECT seq,symbol,body,sha FROM state_history ORDER BY seq'),1):
            v=json.loads(raw)
            if seq!=i or digest(v)!=h or v['symbol']!=s or s not in MARKETS:raise ValueError('state_history_integrity')
            prior[s]=v
        for s,(rows,prospective,v) in prepared.items():
            old=prior.get(s)
            if old:
                for key,items in (('historical',rows),('prospective',prospective)):
                    n=old[key+'_count']
                    if len(items)<n or digest(items[:n])!=old[key+'_digest']:raise ValueError('archive_prefix_changed')
                if old['binding']!=v['binding']:raise ValueError('binding_changed')
            v.update(historical_count=len(rows),historical_digest=digest(rows),prospective_count=len(prospective),prospective_digest=digest(prospective))
            if v!=old:db.execute('INSERT INTO state_history(symbol,body,sha) VALUES(?,?,?)',(s,canonical(v),digest(v)))


def evaluate_index(samples,*,now):
    """Exact loss evaluation for a single normalized equity series.

    No admission decision. Missing opening evidence is not a zero loss.
    The caller must establish identity, capital adjustment and finality.
    """
    from datetime import datetime,timezone,timedelta
    from tradebot.equity_policy_reference_v3 import DEFAULT_LIMITS,ANCHOR_WINDOW,stamp
    if now.tzinfo is None or now.utcoffset() is None:raise ValueError('clock_scope')
    now=now.astimezone(timezone.utc);end=stamp(now)
    if not 2<=len(samples)<=20000:raise ValueError('sample_count')
    values=[];last=0
    for t,v in samples:
        if type(t) is not int or not last<t<=end:raise ValueError('sample_order')
        values.append((t,equity_value(v)));last=t
    day=now.replace(hour=0,minute=0,second=0,microsecond=0)
    week=day-timedelta(days=day.weekday())
    def losses(rows,ref,limit):
        current=max(Fraction(0),1-rows[-1][1]/ref)
        worst=max(max(Fraction(0),1-v/ref) for _,v in rows)
        return dict(current_loss=loss_text(current),maximum_loss=loss_text(worst),
                    reference_limit=str(limit),observed_breach=worst>=Fraction(limit))
    out={}
    for name,start,limit in zip(('daily','weekly'),(day,week),DEFAULT_LIMITS):
        opening=stamp(start);period=[r for r in values if r[0]>=opening]
        if not period or period[0][0]>=opening+ANCHOR_WINDOW*1000000:
            out[name]=dict(current_loss=None,maximum_loss=None,reference_limit=str(limit),observed_breach=None,opening_verified=False)
        else:
            out[name]=dict(losses(period,period[0][1],limit),opening_verified=True)
    peak=values[0][1];worst=Fraction(0)
    for _,v in values:
        peak=max(peak,v);worst=max(worst,1-v/peak)
    limit=DEFAULT_LIMITS[2]
    out['drawdown']=dict(current_loss=loss_text(1-values[-1][1]/peak),maximum_loss=loss_text(worst),reference_limit=str(limit),observed_breach=worst>=Fraction(limit))
    return dict(periods=out,sample_count=len(values),last_observed_us=last,
                gaps_over_180s=sum(b[0]-a[0]>180000000 for a,b in zip(values,values[1:])),
                latest_age_seconds=(end-last)/1000000,execution_authorized=False)


def _evaluate_archives(historical,coverage,evidence,index,now):
    raw=evaluate_index([(t,v) for t,v,_ in historical],now=now)
    adjusted=None
    if index['status']=='conditional_no_capital_index_observed':
        adjusted=evaluate_index([(t,v) for t,v in evidence['values'] if t<=evidence['through']],now=now)
    return dict(historical_raw_only=raw,conditional_index_only=adjusted,
                historical_loss_reconciled=False,broker_finality_verified=False,
                status='unresolved_evidence',execution_authorized=False)

def _reconciliation_state(root,symbol,now):
    """Retain conditional reconciliation evidence, never a release verdict."""
    import json,hashlib
    from tradebot.m20_subaccount_baseline_v3 import read_private
    out=dict(status='unresolved',historical_loss_reconciled=False,
             execution_authorized=False,missing_evidence=[])
    if symbol not in MARKETS:raise ValueError('market_scope')
    def load(name,mode):
        raw=read_private(root/name);v=json.loads(raw)
        if v.get('mode')!=mode or v.get('execution_authorized') is not False or v.get('orders_submitted')!=0:
            raise ValueError('reconciliation_scope')
        if type(v['checked_at']) is not int or not 0<=now.timestamp()-v['checked_at']:
            raise ValueError('reconciliation_time')
        return v,hashlib.sha256(raw).hexdigest()
    try:
        v,h=load('m37-transfer-valuation-audit-v3.json','historical_transfer_valuation_diagnostic')
        a=v['accounts'][symbol]
        for k in ('transfer_count','missing_prior'):
            if type(a[k]) is not int or a[k]<0:raise ValueError('transfer_count')
        if a['missing_prior']>a['transfer_count']:raise ValueError('transfer_count')
        out['initial_transfers']=dict(count=a['transfer_count'],missing_pretransfer_valuations=a['missing_prior'],
                                      source_sha256=h,checked_at=v['checked_at'])
    except (OSError,ValueError,TypeError,KeyError):out['initial_transfers']=None
    try:
        v,h=load('m23-equity-reconciliation-v3.json','historical_equity_reconciliation_diagnostic_only')
        a=v['accounts'][symbol];windows={}
        for k in ('daily','weekly','peak'):
            w=a['windows'][k]
            if w['status']=='conditional_comparison':
                windows[k]=dict(status=w['status'],residual_zero=w['residual_zero'] is True,
                                capital_count=w['counts']['capital'],adjusted_decline=w['adjusted_decline'] is True)
            else:windows[k]=dict(status='unresolved')
        out['endpoints']=dict(windows=windows,source_sha256=h,checked_at=v['checked_at'],
                              age_seconds=int(now.timestamp()-v['checked_at']))
    except (OSError,ValueError,TypeError,KeyError):out['endpoints']=None
    out['missing_evidence']=['historical_account_binding','exact_initial_transfer_valuations',
                             'historical_weekly_opening','broker_finality','approved_migration']
    return out


def prepare_executor_migration(root,legacy_root,*,now=None):
    """Native equity interface for offline executor migration rehearsal.

    Existing risk enforcement is untouched. No report grants trade authority.
    """
    from datetime import datetime,timezone
    from pathlib import Path
    from tradebot.equity_checkpoint_health import checkpoint_health
    now=now or datetime.now(timezone.utc)
    legacy_root=Path(legacy_root)
    out=dict(mode='native_equity_executor_rehearsal',markets={},execution_authorized=False,
             orders_submitted=0,policy_deployed=False,legacy_gate_replaced=False)
    try:
        health=checkpoint_health(legacy_root/'fire-equity-risk.sqlite',at=now)
        out['local_legacy_diagnostic_conditions']=health['blocking_conditions']
        out['authoritative_legacy_status_verified']=False
        out['local_legacy_diagnostic_prerequisites_met']=health['checkpoint_prerequisites_met']
        state=refresh_account_state(root,legacy_root,now=now)
    except Exception:
        out['markets']={s:dict(disposition='wait_equity_review',reason='equity_state_unavailable',execution_authorized=False) for s in MARKETS}
        return out
    for s in MARKETS:
        v=state['markets'][s]['risk_evaluation']
        raw=v['historical_raw_only']['periods']
        out['markets'][s]=dict(disposition='wait_equity_review',
            native_state_loaded=True,
            observed_raw_breaches=[k for k,p in raw.items() if p['observed_breach'] is True],
            historical_loss_reconciled=v['historical_loss_reconciled'],
            broker_finality_verified=v['broker_finality_verified'],
            legacy_protection_retained=True,execution_authorized=False)
    return out
