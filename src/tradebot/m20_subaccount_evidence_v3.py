"""Read-only subaccount evidence. No replacement of the legacy risk ledger."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tradebot.signed_account_context_v3 import read_signed_context,LABELS
from tradebot.owner_connectivity_bridge_v3 import AccountReader
from tradebot.fire_reconciliation import normalize_posting,unique
from tradebot.m20_subaccount_equity_v3 import CAPITAL_TYPES
from tradebot.isolated_performance import POSTED_TYPES
from tradebot.research_collector_v3 import atomic_json
from tradebot.portfolio_equity_guard import stamp

def classify(rows,start,end,pid):
    rows=unique([normalize_posting(p) for p in rows])
    counts=dict(transfers=0,capital=0,trading=0,unclassified=0)
    for p in rows:
        if not start<=p["at_us"]<=end:raise ValueError("history_outside_window")
        if p["asset"]!="USD" or p["product_id"] not in (None,str(pid)):
            counts["unclassified"]+=1
        elif p["type"]=="sub_account_transfer":
            counts["transfers"]+=1
        elif p["type"] in CAPITAL_TYPES:counts["capital"]+=1
        elif p["type"] in POSTED_TYPES:counts["trading"]+=1
        else:counts["unclassified"]+=1
    return counts

def collect(root,children,parent,*,clock=lambda:datetime.now(timezone.utc)):
    out={"mode":"subaccount_evidence_only","markets":{},"parent_equity_included":False,
         "execution_authorized":False,"orders_submitted":0,"paid_ai_requests":0}
    for symbol,label in LABELS.items():
        stage=["signed_context"]
        try:
            child=children[symbol]
            a=read_signed_context(symbol,AccountReader(child,symbol),AccountReader(parent),clock=clock,stage=lambda s:stage.__setitem__(0,s))
            at=datetime.fromisoformat(a["observed_at"])
            end=stamp(at);start=stamp(at-timedelta(days=7))
            stage[0]="wallet_history"
            rows=child.wallet_postings(start,end)
            counts=classify(rows,start,end,a["product"]["product_id"])
            out["markets"][symbol]={"status":"complete_window" if not counts["unclassified"] else "unclassified_postings",
                "subaccount":label,"window_days":7,"window_end":at.isoformat(),"signed_identity_verified":True,
                "signed_wallet_receipt_verified":True,"counts":counts,"snapshot_equity_usd":a["net_equity_usd"],
                "historical_opening_equity_verified":False,"transfer_adjusted_return_verified":False,
                "execution_authorized":False}
        except Exception as e:
            out["markets"][symbol]={"status":"unavailable","stage":stage[0],"reason":type(e).__name__}
    out["checked_at"]=int(clock().timestamp())
    atomic_json(Path(root)/"m20-subaccount-evidence-v3.json",out)
    return out
