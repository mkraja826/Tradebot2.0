"""Read-only prospective wallet evidence. No risk anchor or admission decision."""
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import json,sqlite3,hashlib
from tradebot.m31_equity_evidence_v3 import sample
from tradebot.equity_receipt import validate_receipt
from tradebot.opportunity_journal_v3 import digest
from tradebot.fire_reconciliation import normalize_posting,unique
from tradebot.m20_subaccount_equity_v3 import analyse,CAPITAL_TYPES
from tradebot.isolated_performance import POSTED_TYPES
from tradebot.signed_margin_mode import _user_id
from tradebot.signed_account_context_v3 import LABELS
from tradebot.research_collector_v3 import atomic_json
from tradebot.owner_connectivity_bridge_v3 import AccountReader

def endpoints(path,s):
    if not path.is_file() or path.is_symlink():raise ValueError("ledger_missing")
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        result=[]
        for order in ("ASC","DESC"):
            b,t,raw,h=db.execute("SELECT binding,stamp,body,sha FROM observations WHERE symbol=? ORDER BY stamp "+order+" LIMIT 1",(s,)).fetchone()
            r=json.loads(raw)
            if digest(r)!=h or (r["symbol"],r["account_binding"],r["observed_us"])!=(s,b,t):raise ValueError("archive_scope")
            validate_receipt(r["equity_usd"],r["receipt"],now=datetime.fromtimestamp(t/1e6,timezone.utc))
            if r["receipt"]["received_us"]!=t:raise ValueError("receipt_time")
            result.append(r)
    a,b=result
    if a["account_binding"]!=b["account_binding"] or not 0<b["observed_us"]-a["observed_us"]<=7*86400*1000000:raise ValueError("window_scope")
    return a,b

def compare(s,a,b,rows,pid):
    if a["symbol"]!=s or b["symbol"]!=s or a["account_binding"]!=b["account_binding"]:raise ValueError("identity_scope")
    start,end=a["observed_us"],b["observed_us"]
    rows=unique(rows)
    if any(not start<=r["at_us"]<=end for r in rows):raise ValueError("window_scope")
    boundary=any(r["at_us"]==start or r["at_us"]==end for r in rows)
    unknown=sum(r["asset"]!="USD" or r["product_id"] not in (None,str(pid)) or r["type"] not in CAPITAL_TYPES|POSTED_TYPES for r in rows)
    capital=sum(r["type"] in CAPITAL_TYPES for r in rows)
    out=dict(status="bounded_cashflow_comparison",posting_count=len(rows),capital_posting_count=capital,
             unclassified_count=unknown,boundary_ambiguous=boundary,
             exact_transfer_valuation_verified=False,verified_return=False,
             historical_loss_reconciled=False,execution_authorized=False,
             posting_digest=digest(rows))
    if unknown or boundary:return dict(out,status="unresolved_posting_evidence")
    d=analyse(s,a["equity_usd"],b["equity_usd"],[dict(r,symbol=s) for r in rows],start_us=start,end_us=end,complete=True)
    return dict(out,raw_cashflow_comparison_available=d["status"]=="offline_calculated",
                transfer_adjusted_risk_index_available=False)

def collect(root,children,parent,*,clock=lambda:datetime.now(timezone.utc)):
    root=Path(root);out=dict(mode="prospective_cashflow_evidence_only",markets={},
        execution_authorized=False,orders_submitted=0,policy_changed=False)
    for s in LABELS:
        try:
            c=children[s]
            a,b=endpoints(root/"m31-equity-evidence-v3.sqlite",s)
            current=sample(s,c,parent,clock)
            if current["account_binding"]!=a["account_binding"]:raise ValueError("archive_account_mismatch")
            reader=AccountReader(c,s)
            p=reader._request("GET","/v2/products/"+s)["result"]
            if p["symbol"]!=s or type(p["id"]) is not int:raise ValueError("product_scope")
            raw=c.wallet_postings(a["observed_us"],b["observed_us"])
            prefs=reader._request("GET","/v2/users/trading_preferences",auth=True)["result"]
            if hashlib.sha256(("delta-demo:"+_user_id(prefs["user_id"])).encode()).hexdigest()!=a["account_binding"]:raise ValueError("account_changed")
            rows=[normalize_posting(x) for x in raw]
            r=compare(s,a,b,rows,p["id"])
            r.update(window_start_us=a["observed_us"],window_end_us=b["observed_us"],
                     account_binding_verified=True,requested_window_returned=True)
        except Exception as exc:r=dict(status="unavailable",reason=type(exc).__name__)
        out["markets"][s]=r
    out["checked_at"]=int(clock().timestamp())
    atomic_json(root/"m31-cashflow-evidence-v3.json",out)
    return out
