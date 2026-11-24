"""Prospective subaccount performance diagnostics, not execution prerequisites."""
import json,hashlib
from datetime import datetime,timezone
from pathlib import Path
from tradebot.m20_subaccount_baseline_v3 import read_private,TARGET
from tradebot.m20_subaccount_equity_v3 import analyse
from tradebot.signed_account_context_v3 import LABELS,read_signed_context
from tradebot.owner_connectivity_bridge_v3 import AccountReader
from tradebot.fire_reconciliation import normalize_posting,unique
from tradebot.portfolio_equity_guard import stamp
from tradebot.research_collector_v3 import atomic_json

MAX_WINDOW_US=7*86400*1000000

def project(symbol,base,a,rows):
    if base["subaccount"]!=LABELS[symbol] or a["symbol"]!=symbol or a["subaccount"]!=base["subaccount"] or a["signed_account_verified"] is not True or a["wallet_receipt_verified"] is not True:
        raise ValueError("unverified_scope")
    start=stamp(datetime.fromisoformat(base["observed_at"]))
    end=stamp(datetime.fromisoformat(a["observed_at"]))
    if not 0<end-start<=MAX_WINDOW_US:raise ValueError("unsupported_window")
    pid=str(a["product"]["product_id"])
    rows=unique([normalize_posting(p) for p in rows])
    if any(p["product_id"] not in (None,pid) for p in rows):
        raise ValueError("unexpected_product")
    result=analyse(symbol,base["opening_equity_usd"],a["net_equity_usd"],
                   [dict(p,symbol=symbol) for p in rows],start_us=start,end_us=end,complete=True)
    result.update(mode="signed_forward_diagnostic_only",baseline_at=base["observed_at"],
                  observed_at=a["observed_at"],current_identity_verified=True,
                  baseline_identity_binding="label_and_roster_not_persistent_account_id",
                  wallet_receipt_verified=True,history_window_complete=True,
                  is_verified_return=False,historical_loss_status="not_reconciled",
                  execution_authorized=False)
    return result

def collect(root,children,parent,*,clock=lambda:datetime.now(timezone.utc)):
    root=Path(root);raw=read_private(root/TARGET);b=json.loads(raw)
    if b.get("mode")!="forward_subaccount_baseline_diagnostic_only" or b.get("execution_authorized") is not False or b.get("parent_equity_included") is not False or b.get("historical_checkpoint_replaced") is not False or set(b["markets"])!=set(LABELS):
        raise ValueError("invalid_baseline")
    out={"mode":"subaccount_performance_monitor_only","baseline_sha256":hashlib.sha256(raw).hexdigest(),
         "markets":{},"parent_equity_included":False,"execution_authorized":False,
         "orders_submitted":0,"paid_ai_requests":0}
    for s in LABELS:
        try:
            child=children[s];base=b["markets"][s]
            a=read_signed_context(s,AccountReader(child,s),AccountReader(parent),clock=clock)
            start=stamp(datetime.fromisoformat(base["observed_at"]))
            end=stamp(datetime.fromisoformat(a["observed_at"]))
            if not 0<end-start<=MAX_WINDOW_US:raise ValueError("unsupported_window")
            rows=child.wallet_postings(start,end)
            out["markets"][s]=project(s,base,a,rows)
            out["markets"][s]["position_snapshot"]={
                "observed_at":a["observed_at"],"status":"signed_read_only",
                "open_order_count":a["open_order_count"],
                "positions":[{k:p.get(k) for k in ("symbol","side","size","entry","mark","liquidation","unrealized_pnl")} |
                  {"protection":{k:p.get("protection",{}).get(k) for k in ("status","stop_loss","take_profit")}} for p in a["positions"]]}

        except Exception as exc:
            out["markets"][s]={"status":"unavailable","reason":type(exc).__name__,
                                "execution_authorized":False}
    out["checked_at"]=int(clock().timestamp())
    atomic_json(root/"m20-subaccount-performance-v3.json",out)
    return out
