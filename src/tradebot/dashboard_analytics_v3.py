"""Allowlisted research dashboard analytics, no broker or provider clients."""
import json
from math import isfinite

REPORTS={
 "campaign":("m19-provider-campaign-v3.json",150,"paid_paper_only_campaign"),
 "paper":("m21-paper-learning-v3.json",660,"paper_learning_diagnostic_only"),
 "equity":("m20-subaccount-performance-v3.json",660,"subaccount_performance_monitor_only"),
 "settlement":("m21-settlement-learning-v3.json",600,"settlement_learning_research_only")}
FIELDS={
 "paper":("LONG","SHORT","WAIT","validated_paper_proposal","transport_outcome_unknown","response_rejected","reserved_outcome_unknown","path_observed","path_pending","path_missing_candles","unlinked"),
 "equity":("status","baseline_at","observed_at","adjusted_equity_change_usd","net_capital_flow_usd","posted_trading_cashflow_usd","unexplained_or_unrealized_change_usd","history_window_complete","is_verified_return"),
 "settlement":("status","fire_receipts","verified_closed","unverified_or_open","signed_fill_count","signed_wallet_posting_count","verified_wins","verified_losses","verified_subset_net_usd","sample_status")}
def safe(x):
    if type(x) is float:return x if isfinite(x) else None
    if type(x) is str:return x[:160]
    return x if x is None or type(x) in (int,bool) else None
def select(d,keys):
    return {k:safe(d[k]) for k in keys if k in d}
def analytics(root,now):
    out={}
    for key,(filename,limit,mode) in REPORTS.items():
        try:
            p=root/filename
            if p.is_symlink():raise ValueError()
            with p.open("rb") as f:raw=f.read(2000001)
            if len(raw)>2000000:raise ValueError()
            r=json.loads(raw)
            if r["mode"]!=mode or r["execution_authorized"] is not False or r["orders_submitted"]!=0:raise ValueError()
            t=r["checked_at"]
            if type(t) is not int or not 0<=now-t:raise ValueError()
            item=dict(state="fresh" if now-t<=limit else "historical",age_seconds=int(now-t),markets={})
            if key=="campaign":
                item["budget"]=select(r["budget"],("limit","reserved","remaining"))
                item["status"]=safe(r["status"])
            else:
                for s in ("BTCUSD","XAUTUSD"):
                    a=r["markets"].get(s,{})
                    item["markets"][s]=select(a,FIELDS[key])
                    if key=="settlement":
                        item["markets"][s]["reasons"]=select(a.get("unverified_reasons",{}),("broker_order_not_submitted","unattributed_wallet_posting","missing_broker_funding_total","broker_evidence_shared_between_trades"))
                if key=="paper":
                    item["groups"]=[select(g,("symbol","decision_action","horizon_minutes","observed","pending","missing","distinct_observed_events","mean_signal_direction_return_pct","positive_signal_fraction")) for g in r.get("signal_path_summary",[])[:18] if g.get("symbol") in ("BTCUSD","XAUTUSD")]
            out[key]=item
        except (OSError,ValueError,KeyError,TypeError,AttributeError):
            out[key]={"state":"unavailable","age_seconds":None,"markets":{}}
    return out
