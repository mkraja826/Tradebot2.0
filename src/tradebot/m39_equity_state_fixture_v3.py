"""Durable synthetic replay fixture only; no live inputs or admission interface."""
import hashlib,json,sqlite3
from contextlib import closing
from pathlib import Path
from tradebot.equity_policy_v3 import account_research,MARKETS

def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(v):return hashlib.sha256(v.encode()).hexdigest()

def replay(path,fixture):
    if fixture.get('mode')!='synthetic_policy_research' or fixture.get('execution_authorized') is not False or fixture.get('complete_fixture') is not True:raise ValueError('synthetic_complete_only')
    s=fixture['symbol'];account=fixture['fixture_account']
    if s not in MARKETS or account!='synthetic-'+('btc' if s=='BTCUSD' else 'gold'):raise ValueError('fixture_binding')
    result=account_research(fixture)
    events=[canonical(e) for e in fixture['events']]
    path=Path(path)
    if path.name!='m39-fixture.sqlite' or path.is_symlink():raise ValueError('fixture_path')
    with closing(sqlite3.connect(path,timeout=5,isolation_level=None)) as db:
        db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('CREATE TABLE IF NOT EXISTS fixture_events(symbol TEXT NOT NULL, seq INTEGER NOT NULL, body TEXT NOT NULL, sha TEXT NOT NULL, PRIMARY KEY(symbol,seq))')
            if db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise ValueError('integrity')
            prior=db.execute('SELECT seq,body,sha FROM fixture_events WHERE symbol=? ORDER BY seq',(s,)).fetchall()
            if len(prior)>len(events):raise ValueError('history_truncation')
            for i,(seq,body,h) in enumerate(prior):
                if seq!=i or digest(body)!=h or body!=events[i]:raise ValueError('history_conflict')
            db.executemany('INSERT INTO fixture_events VALUES(?,?,?,?)',[(s,i,body,digest(body)) for i,body in enumerate(events) if i>=len(prior)])
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
    return dict(result,persisted_event_count=len(events),new_events=len(events)-len(prior),durable_fixture_only=True)


def history_checkpoint(path):
    """Fingerprint the synthetic history; never initialize missing state."""
    p=Path(path)
    if p.name!='m39-fixture.sqlite' or not p.is_file() or p.is_symlink():raise ValueError('fixture_path')
    with closing(sqlite3.connect(p.absolute().as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise ValueError('integrity')
        rows=db.execute('SELECT symbol,seq,body,sha FROM fixture_events ORDER BY symbol,seq').fetchall()
    counts={s:0 for s in MARKETS}
    for s,seq,body,h in rows:
        if s not in counts or seq!=counts[s] or digest(body)!=h:raise ValueError('history_conflict')
        counts[s]+=1
    return dict(mode='synthetic_checkpoint_only',counts=counts,sha256=digest(canonical(rows)))


def verify_checkpoint(path,expected):
    """Compare with a previously retained trusted fixture checkpoint."""
    if history_checkpoint(path)!=expected:raise ValueError('checkpoint_mismatch')
    return True
