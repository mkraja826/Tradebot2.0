"""Read-only sampled equity reporting. No admission, order or policy interface."""
import json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from fractions import Fraction
from tradebot.m31_loss_observations_v3 import read_window
from tradebot.m25_equity_policy_research_v3 import equity_value,loss_text
from tradebot.equity_policy_v3 import MARKETS
from tradebot.m20_subaccount_baseline_v3 import read_private
from tradebot.research_collector_v3 import atomic_json

def metrics(rows):
    if len(rows)<2:raise ValueError('insufficient_samples')
    times=[t for t,_ in rows]
    if any(type(t) is not int or t<=0 for t in times) or any(b<=a for a,b in zip(times,times[1:])):raise ValueError('invalid_times')
    peak=Fraction(0);worst=Fraction(0)
    for _,v in rows:
        equity=equity_value(v);peak=max(peak,equity);worst=max(worst,1-equity/peak)
    return dict(sample_count=len(rows),first_us=times[0],last_us=times[-1],gaps_over_180s=sum(b-a>180000000 for a,b in zip(times,times[1:])),maximum_sampled_raw_drawdown=loss_text(worst),end_sampled_raw_drawdown=loss_text(1-equity/peak))

def report(root,*,now=None):
    root=Path(root);now=datetime.now(timezone.utc) if now is None else now
    out=dict(mode='sampled_subaccount_equity_report_only',checked_at=int(now.timestamp()),markets={},execution_authorized=False,orders_submitted=0,policy_changed=False,historical_equivalence_verified=False,broker_finality_verified=False)
    try:
        raw=json.loads(read_private(root/'m31-cashflow-evidence-v3.json'))
        age=now.timestamp()-raw['checked_at']
        if raw['mode']!='prospective_cashflow_evidence_only' or raw['execution_authorized'] is not False or not 0<=age<=600:raise ValueError('report_scope_or_age')
    except (OSError,ValueError,KeyError,TypeError):raw={};age=None
    for s in MARKETS:
        try:
            a=raw['markets'][s]
            if a['status']!='bounded_cashflow_comparison' or a['account_binding_verified'] is not True or a['requested_window_returned'] is not True or a['boundary_ambiguous'] is not False or a['capital_posting_count']!=0 or a['unclassified_count']!=0:raise ValueError('unresolved_cashflow')
            rows=read_window(root/'m31-equity-evidence-v3.sqlite',s,a['window_start_us'],a['window_end_us'])
            m=metrics(rows);m.update(status='historical_sampled_raw_only',cashflow_report_age_seconds=int(age),window_end_age_seconds=int(now.timestamp()-m['last_us']/1e6),capital_postings_reported=0,unclassified_postings_reported=0,transfer_adjusted_risk_index_verified=False)
            if m['window_end_age_seconds']<0:raise ValueError('future_observation')
        except (OSError,ValueError,KeyError,TypeError,ArithmeticError,sqlite3.Error) as exc:m=dict(status='unavailable_or_unresolved',reason=type(exc).__name__)
        out['markets'][s]=m
    atomic_json(root/'m38-equity-report-v3.json',out)
    return out

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    print(json.dumps(report(p.parse_args().directory),sort_keys=True))
