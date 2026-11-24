"""Independent review evidence only; no risk policy or order mutations."""
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from tradebot.delta import DEMO_API
from tradebot.signed_margin_mode import _user_id,_parent_signed_subaccount_mode
from tradebot.signed_account_context_v3 import LABELS,read_signed_context
from tradebot.owner_connectivity_bridge_v3 import AccountReader
from tradebot.fire_reconciliation import normalize_posting,unique
from tradebot.portfolio_equity_guard import stamp
from tradebot.research_collector_v3 import atomic_json

EXPECTED={"BTCUSD":("94.12","29.40","149.58"),"XAUTUSD":("100","5.88","70.59","100")}

def funding_evidence(symbol,rows,start,end):
    rows=unique([normalize_posting(p) for p in rows])
    if any(not start<=p["at_us"]<=end for p in rows):raise ValueError("outside_window")
    transfers=[p for p in rows if p["type"]=="sub_account_transfer"]
    valid=all(p["asset"]=="USD" and p["product_id"] is None for p in transfers)
    incoming=[Decimal(p["amount"]) for p in transfers if p["asset"]=="USD" and Decimal(p["amount"])>0]
    expected=sorted(Decimal(x) for x in EXPECTED[symbol])
    return dict(transfer_count=len(transfers),incoming_transfer_count=len(incoming),
                owner_amount_multiset_matches=valid and len(transfers)==len(incoming) and sorted(incoming)==expected,
                incoming_transfer_total_usd=str(sum(incoming,Decimal(0))),
                transfer_counterparty_verified=False,
                complete_requested_window=True,opening_equity_verified=False)

def inspect(s,child,parent,clock):
    for client in (child,parent):
        if getattr(client,"base_url",None)!=DEMO_API or getattr(client,"allow_orders",None) is not False:raise ValueError("readonly_required")
    c=AccountReader(child,s);p=AccountReader(parent)
    before=c._request("GET","/v2/users/trading_preferences",auth=True)["result"]
    uid=_user_id(before["user_id"])
    if _parent_signed_subaccount_mode(uid,before.get("margin_mode"),parent_exchange=p,expected_label=LABELS[s])!="isolated":raise ValueError("identity")
    roster=p._request("GET","/v2/sub_accounts",auth=True)["result"]
    row,=(r for r in roster if _user_id(r["id"])==uid)
    ctx=read_signed_context(s,c,p,clock=clock)
    end=stamp(datetime.fromisoformat(ctx["observed_at"]));start=end-7*86400*1000000
    a=funding_evidence(s,child.wallet_postings(start,end),start,end)
    after=c._request("GET","/v2/users/trading_preferences",auth=True)["result"]
    if _user_id(after["user_id"])!=uid:raise ValueError("identity_changed")
    a.update(status="bounded_signed_evidence",current_identity_verified=True,
             creation_field_present=row.get("created_at") is not None,
             creation_timestamp_verified=False,history_days=7)
    if a["creation_field_present"]:
        try:
            t=datetime.fromisoformat(str(row["created_at"]).replace("Z","+00:00"))
            if t.tzinfo is not None and 0<stamp(t)<=end:
                a.update(roster_creation_at=t.isoformat(),creation_timestamp_verified=True)
        except (TypeError,ValueError,OverflowError):pass
    return a

def collect(root,children,parent,*,clock=lambda:datetime.now(timezone.utc)):
    out=dict(mode="independent_inception_evidence_only",markets={},execution_authorized=False,orders_submitted=0,paid_ai_requests=0,policy_changed=False)
    for s in LABELS:
        try:a=inspect(s,children[s],parent,clock)
        except Exception as e:a=dict(status="unavailable",reason=type(e).__name__)
        out["markets"][s]=dict(a,historical_identity_verified=False,inception_equity_verified=False)
    out["checked_at"]=int(clock().timestamp())
    atomic_json(Path(root)/"m25-inception-evidence-v3.json",out)
    return out
