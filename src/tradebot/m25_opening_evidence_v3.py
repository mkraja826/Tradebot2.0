"""Retrospective accounting evidence only; never supplies an opening risk anchor."""
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
from contextlib import closing
import sqlite3,json
from tradebot.equity_receipt import validate_receipt
from tradebot.portfolio_equity_guard import stamp,amount
from tradebot.fire_reconciliation import normalize_posting,unique
from tradebot.m20_subaccount_equity_v3 import CAPITAL_TYPES
from tradebot.isolated_performance import POSTED_TYPES
from tradebot.m25_inception_evidence_v3 import inspect
from tradebot.research_collector_v3 import atomic_json

def earliest(path):
    if path.is_symlink() or not path.is_file():raise ValueError("ledger_unavailable")
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        t,e,origin=db.execute("SELECT observed_us,equity_usd,origin FROM equity_evidence ORDER BY observed_us LIMIT 1").fetchone()
        r=db.execute("SELECT receipt FROM equity_read_receipts WHERE observed_us=?",(t,)).fetchone()
        at=datetime.fromtimestamp(t/1e6,timezone.utc)
        if origin!="delta_demo_signed_wallet" or not r or stamp(validate_receipt(e,json.loads(r[0]),now=at))!=t:raise ValueError("receipt_unverified")
        return t,amount(e)

def compare(created,first,equity,rows,pid):
    if not 0<created<first:raise ValueError("invalid_window")
    rows=unique(rows)
    cap=Decimal(0);trade=Decimal(0);unknown=0
    for p in rows:
        if not created<=p["at_us"]<=first:raise ValueError("outside_window")
        if p["asset"]!="USD" or p["product_id"] not in (None,str(pid)):unknown+=1
        elif p["type"] in CAPITAL_TYPES:cap+=Decimal(p["amount"])
        elif p["type"] in POSTED_TYPES:trade+=Decimal(p["amount"])
        else:unknown+=1
    return dict(posting_count=len(rows),unclassified_count=unknown,
                conditional_cashflow_matches_first_equity=(cap+trade==equity) if not unknown else None,
                historical_identity_verified=False,inception_equity_verified=False,
                risk_anchor_created=False)

def discrepancy(created,first,equity,rows,pid,nearby):
    """Describe evidence; never round away a discrepancy or infer a balance."""
    from collections import Counter
    base=compare(created,first,equity,rows,pid)
    rows=unique(rows)
    counts=dict(Counter(p["type"] for p in rows))
    result=dict(posting_type_counts=counts,precision_explains_difference=False,
                initial_credit_present=any(p["type"] in ("deposit","external_deposit","fund_deposit","fund_wallet_deposit") and Decimal(p["amount"])>0 for p in rows),
                nearby_postings_count=len(unique(nearby)),timing_explanation_verified=False,
                accounting_explanation_verified=False)
    if base["unclassified_count"]:return dict(result,discrepancy_class="unclassified")
    residual=equity-sum((Decimal(p["amount"]) for p in rows),Decimal(0))
    result["discrepancy_class"]=("exact" if not residual else "sub_cent" if abs(residual)<Decimal("0.01") else "one_cent_or_more")
    result["precision_explains_difference"]=False
    result["first_equity_above_net_postings"]=residual>0
    return result

def wallet_chain(raw,equity,start,end):
    """Check broker-reported transaction balances, not historical net equity."""
    pairs={}
    for x in raw:
        p=normalize_posting(x)
        if not start<=p["at_us"]<=end or p["asset"]!="USD":raise ValueError("wallet_scope")
        b=Decimal(str(x["balance"]))
        if not b.is_finite():raise ValueError("invalid_balance")
        item=(p,b)
        if p["id"] in pairs and pairs[p["id"]]!=item:raise ValueError("conflicting_balance")
        pairs[p["id"]]=item
    rows=sorted(pairs.values(),key=lambda item:item[0]["at_us"])
    if not rows:return dict(balance_chain_status="no_postings",historical_net_equity_verified=False)
    if len({p["at_us"] for p,b in rows})!=len(rows):return dict(balance_chain_status="ambiguous_order",historical_net_equity_verified=False)
    coherent=all(b1+Decimal(p2["amount"])==b2 for (p1,b1),(p2,b2) in zip(rows,rows[1:]))
    initial=rows[0][1]-Decimal(rows[0][0]["amount"])
    final=rows[-1][1]
    return dict(balance_chain_status="consistent" if coherent else "inconsistent",
                implied_pre_first_posting_wallet_nonzero=initial!=0,
                implied_pre_first_posting_wallet_positive=initial>0,
                last_posting_wallet_matches_first_equity=final==equity,
                historical_net_equity_verified=False)

def collect(root,children,parent,*,legacy_root=Path("/home/support/Tradebot2.0/data"),clock=lambda:datetime.now(timezone.utc)):
    out=dict(mode="opening_equity_evidence_only",markets={},execution_authorized=False,orders_submitted=0,paid_ai_requests=0,policy_changed=False)
    for s,d in (("BTCUSD","btc-isolated"),("XAUTUSD","gold-isolated")):
        try:
            child=children[s];a=inspect(s,child,parent,clock)
            if not a["creation_timestamp_verified"]:raise ValueError("creation_unverified")
            start=stamp(datetime.fromisoformat(a["roster_creation_at"]))
            end,equity=earliest(legacy_root/d/"fire-equity-risk.sqlite")
            if not 0<end-start<=7*86400*1000000:raise ValueError("invalid_window")
            product=child._request("GET","/v2/products/"+s)["result"]
            if product["symbol"]!=s or type(product["id"]) is not int:raise ValueError("product_unverified")
            pid=product["id"]
            raw=child.wallet_postings(start,end)
            rows=[normalize_posting(p) for p in raw]
            r=compare(start,end,equity,rows,pid)
            try:r.update(wallet_chain(raw,equity,start,end))
            except (ValueError,KeyError,TypeError,ArithmeticError):r.update(balance_chain_status="unavailable_or_invalid",historical_net_equity_verified=False)

            nearby=[normalize_posting(p) for p in child.wallet_postings(end,end+60000000)]
            if any(not end<=p["at_us"]<=end+60000000 for p in nearby):raise ValueError("nearby_window")
            nearby=[p for p in nearby if p["at_us"]>end]
            r.update(discrepancy(start,end,equity,rows,pid,nearby))

            fills=child.product_fills(pid,start_time_us=start,end_time_us=end)
            r.update(status="conditional_opening_comparison",first_observation_at=datetime.fromtimestamp(end/1e6,timezone.utc).isoformat(),creation_at=a["roster_creation_at"],first_receipt_verified=True,fill_count=len(fills),history_window_complete=True)
        except Exception as e:r=dict(status="unavailable",reason=type(e).__name__)
        out["markets"][s]=r
    out["checked_at"]=int(clock().timestamp())
    atomic_json(Path(root)/"m25-opening-evidence-v3.json",out)
    return out
