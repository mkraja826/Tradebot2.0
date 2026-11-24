"""Local, non-mutating V3 administration diagnostics. No shell or broker writes."""
import argparse,json,sqlite3
from pathlib import Path
from contextlib import closing
from tradebot.opportunity_journal_v3 import digest
from tradebot.equity_policy_v3 import MARKETS

STATE=Path(__file__).resolve().parents[2]/'research-data/v3-equity-state.sqlite'

def status(path,symbol):
    if symbol not in MARKETS:raise ValueError('unsupported_market')
    if path.is_symlink() or not path.is_file():raise ValueError('state_unavailable')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise ValueError('state_integrity')
        last=None
        for i,(seq,s,raw,h) in enumerate(db.execute('SELECT seq,symbol,body,sha FROM state_history ORDER BY seq'),1):
            v=json.loads(raw)
            if seq!=i or s not in MARKETS or v.get('symbol')!=s or digest(v)!=h:raise ValueError('state_integrity')
            if s==symbol:last=v
        if last is None:raise ValueError('state_unavailable')
    risk=last['risk_evaluation']
    return dict(market=symbol,mode='stored_state_diagnostic_only',
                historical_samples=last['historical_count'],
                prospective_samples=last['prospective_count'],
                historical_raw_drawdown=last['historical_raw']['maximum_sampled_raw_drawdown'],
                observed_periods=risk['historical_raw_only']['periods'],
                last_observed_us=risk['historical_raw_only']['last_observed_us'],
                historical_loss_reconciled=False,broker_finality_verified=False,
                active_trading_gate_status='not_verified_by_this_tool',
                execution_authorized=False,policy_deployed=False)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['status'])
    p.add_argument('market',choices=MARKETS)
    a=p.parse_args()
    try:result=status(STATE,a.market)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        print(json.dumps(dict(status='unavailable',execution_authorized=False)))
        return 1
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=='__main__':raise SystemExit(main())
