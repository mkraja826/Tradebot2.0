"""Prospective evidence archive only; does not reset or replace existing risk history."""
import os,sqlite3,json,hashlib
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
from tradebot.owner_connectivity_bridge_v3 import AccountReader
from tradebot.signed_margin_mode import _user_id,_parent_signed_subaccount_mode
from tradebot.signed_account_context_v3 import LABELS
from tradebot.equity_receipt import validate_receipt
from tradebot.opportunity_journal_v3 import canonical,digest
from tradebot.research_collector_v3 import atomic_json

def sample(s,child,parent,clock):
    r=AccountReader(child,s);p=AccountReader(parent)
    def prefs():return r._request("GET","/v2/users/trading_preferences",auth=True)["result"]
    a=prefs();uid=_user_id(a["user_id"])
    if _parent_signed_subaccount_mode(uid,a.get("margin_mode"),parent_exchange=p,expected_label=LABELS[s])!="isolated":
        raise ValueError("identity_scope")
    w=r.wallet_balances()
    b=prefs()
    if _user_id(b["user_id"])!=uid or b.get("margin_mode")!=a.get("margin_mode"):
        raise ValueError("identity_changed")
    equity=w["meta"]["net_equity"];receipt=w["equity_read_receipt"]
    validate_receipt(equity,receipt,now=clock())
    return dict(symbol=s,account_binding=hashlib.sha256(("delta-demo:"+uid).encode()).hexdigest(),
                observed_us=receipt["received_us"],equity_usd=str(equity),receipt=receipt)

def store(path,row,*,now):
    path=Path(path)
    if path.is_symlink():raise ValueError("untrusted_path")
    fd=os.open(path,os.O_CREAT|os.O_NOFOLLOW|os.O_RDWR,0o600)
    try:
        st=os.fstat(fd)
        if st.st_uid!=os.geteuid() or st.st_mode&0o077 or st.st_nlink!=1:raise ValueError("private_ledger_required")
    finally:os.close(fd)
    s=row["symbol"];binding=row["account_binding"];t=row["observed_us"]
    if s not in LABELS or len(binding)!=64 or any(c not in "0123456789abcdef" for c in binding):raise ValueError("invalid_scope")
    validate_receipt(row["equity_usd"],row["receipt"],now=now)
    if type(t) is not int or row["receipt"]["received_us"]!=t:raise ValueError("receipt_time")
    body=canonical(row)
    with closing(sqlite3.connect(path,timeout=5)) as db,db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE IF NOT EXISTS observations(symbol TEXT NOT NULL,binding TEXT NOT NULL,stamp INTEGER NOT NULL,body TEXT NOT NULL,sha TEXT NOT NULL,PRIMARY KEY(symbol,stamp))")
        for op in ("UPDATE","DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{op.lower()} BEFORE {op} ON observations BEGIN SELECT RAISE(ABORT,'immutable evidence'); END")
        db.execute("BEGIN IMMEDIATE")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        if db.execute("SELECT 1 FROM observations WHERE (symbol=? AND binding<>?) OR (symbol<>? AND binding=?) LIMIT 1",(s,binding,s,binding)).fetchone():raise ValueError("binding_conflict")
        last=db.execute("SELECT stamp,sha FROM observations WHERE symbol=? ORDER BY stamp DESC LIMIT 1",(s,)).fetchone()
        if last and t<=last[0]:
            if t==last[0] and last[1]==digest(row):return "duplicate"
            raise ValueError("nonmonotonic_evidence")
        db.execute("INSERT INTO observations VALUES(?,?,?,?,?)",(s,binding,t,body,digest(row)))
    return "recorded"

def collect(root,children,parent,*,clock=lambda:datetime.now(timezone.utc)):
    root=Path(root)
    out=dict(mode="prospective_equity_evidence_only",markets={},execution_authorized=False,
             orders_submitted=0,policy_changed=False,historical_loss_reconciled=False)
    for s in LABELS:
        try:
            row=sample(s,children[s],parent,clock)
            state=store(root/"m31-equity-evidence-v3.sqlite",row,now=clock())
            r=dict(status=state,account_binding_recorded=True,receipt_verified=True)
        except Exception as exc:r=dict(status="unavailable",reason=type(exc).__name__)
        out["markets"][s]=r
    out["checked_at"]=int(clock().timestamp())
    atomic_json(root/"m31-equity-evidence-v3.json",out)
    return out
