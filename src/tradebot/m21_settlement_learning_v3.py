"""Independent signed settlement research; no orders or model calls."""
from collections import Counter
from decimal import Decimal
from pathlib import Path
from datetime import datetime,timezone
from tradebot.isolated_performance import collect_account_performance
from tradebot.signed_account_context_v3 import LABELS,read_signed_context
from tradebot.owner_connectivity_bridge_v3 import AccountReader
from tradebot.research_collector_v3 import atomic_json

def project(symbol,r):
    if r["symbol"]!=symbol or r["status"]!="complete_broker_window" or r["source"]!="signed_delta_india_demo_readonly":
        raise ValueError("invalid_evidence")
    rows=r["trade_rows"]; n=r["fire_trade_count_in_window"]
    out=dict(status="complete_broker_window",as_of=r["as_of"],window_days=r["window_days"],fire_receipts=n,
             verified_closed=r["broker_reconciled_closed_trades"],unverified_or_open=r["unverified_or_open_trades"],
             signed_fill_count=r["signed_fill_count"],signed_wallet_posting_count=r["signed_wallet_posting_count"],
             scope="legacy_demo_settlements_only",execution_authorized=False,model_quality=None,
             entry_quality=None,exit_timing_quality=None,stop_target_effectiveness=None,
             verified_subset_net_usd=None,verified_subset_fees_usd=None,verified_subset_funding_usd=None)
    if r["history_truncated"] or len(rows)!=n:
        out["status"]="incomplete_receipt_coverage";return out
    verified=[];reasons=Counter();timing=Counter()
    for row in rows:
        if row["symbol"]!=symbol:raise ValueError("wrong_market")
        if row["is_net_realized_pnl"] is not True:
            reasons[row["reason"]]+=1
            diagnostic=row.get("wallet_timing_evidence",{})
            if diagnostic.get("status")=="timing_counts_only":
                timing["receipts_with_timing_evidence"]+=1
                for k in ("nonowned_during_position","nonowned_after_flat_fill","after_flat_without_order_or_fill_ref"):
                    v=diagnostic.get(k)
                    if type(v) is not int or v<0:raise ValueError("invalid_timing_count")
                    timing["receipts_with_"+k]+=int(v>0)
            continue
        if row["reconciliation_status"]!="broker_reconciled":raise ValueError("unverified_settlement")
        v=tuple(Decimal(row[k]) for k in ("net_realized_pnl_usd","gross_realized_pnl_usd","fees_usd","funding_usd"))
        if any(not x.is_finite() for x in v) or v[0]!=v[1]-v[2]+v[3]:raise ValueError("pnl_mismatch")
        verified.append(v)
    if len(verified)!=out["verified_closed"] or len(verified)+out["unverified_or_open"]!=n:raise ValueError("count_mismatch")
    out["unverified_reasons"]=dict(reasons)
    out["wallet_attribution_diagnostics"]=dict(timing)
    out["verified_wins"]=sum(v[0]>0 for v in verified)
    out["verified_losses"]=sum(v[0]<0 for v in verified)
    out["sample_status"]="insufficient_sample" if len(verified)<30 else "descriptive_only"
    if verified:
        for k,i in (("verified_subset_net_usd",0),("verified_subset_fees_usd",2),("verified_subset_funding_usd",3)):
            out[k]=str(sum(v[i] for v in verified))
    return out

def collect(root,children,parent,*,legacy_root=Path("/home/support/Tradebot2.0/data"),clock=lambda:datetime.now(timezone.utc)):
    out=dict(mode="settlement_learning_research_only",markets={},execution_authorized=False,orders_submitted=0,paid_ai_requests=0,parent_equity_included=False)
    for s,label in LABELS.items():
        stage="identity"
        try:
            child=children[s]
            read_signed_context(s,AccountReader(child,s),AccountReader(parent),clock=clock)
            stage="reconciliation"
            raw=collect_account_performance(child,legacy_root/("btc-isolated" if label=="BTC" else "gold-isolated"),s,now=clock(),full_research_rows=True)
            out["markets"][s]=project(s,raw)
        except Exception as exc:
            out["markets"][s]=dict(status="unavailable",stage=stage,reason=type(exc).__name__,execution_authorized=False)
    out["checked_at"]=int(clock().timestamp())
    atomic_json(Path(root)/"m21-settlement-learning-v3.json",out)
    return out
