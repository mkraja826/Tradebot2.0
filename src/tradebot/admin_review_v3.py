"""Non-authorizing policy review through the existing VM administration workflow."""
import argparse,hashlib,json,time
from pathlib import Path
from tradebot.admin_v3 import STATE
from tradebot.equity_policy_v3 import MARKETS
from tradebot.equity_policy_reference_v3 import DEFAULT_LIMITS
from tradebot.dispatch_readiness_v3 import native_equity_context

def review(root,*,now=None):
    now=time.time() if now is None else now
    src=Path(__file__).parent
    files=('equity_policy_v3.py','equity_policy_reference_v3.py')
    return dict(mode='v3_policy_review_only',checked_at=int(now),
        policy_source_hashes={f:hashlib.sha256((src/f).read_bytes()).hexdigest() for f in files},
        reference_limits=dict(zip(('daily','weekly','drawdown'),map(str,DEFAULT_LIMITS))),
        reference_limits_approved_for_production=False,
        markets={s:native_equity_context(root,s,now=now) for s in MARKETS},
        active_gate_status='requires_authoritative_checkpoint_status',
        production_policy_replaced=False,execution_authorized=False)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.parse_args()
    print(json.dumps(review(STATE.parent),sort_keys=True))
if __name__=='__main__':main()
