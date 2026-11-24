"""Append-only rolling wallet-query evidence. No risk index or release authority."""
import os,json,sqlite3
from pathlib import Path
from contextlib import closing
from tradebot.opportunity_journal_v3 import canonical,digest
from tradebot.fire_reconciliation import unique
from tradebot.m20_subaccount_equity_v3 import CAPITAL_TYPES
from tradebot.isolated_performance import POSTED_TYPES
from tradebot.signed_account_context_v3 import LABELS

DAY=86400*1000000

def record(path,s,binding,start,end,observed,rows,pid):
    if s not in LABELS or not isinstance(binding,str) or len(binding)!=64 or any(c not in "0123456789abcdef" for c in binding):
        raise ValueError("scope")
    if any(type(x) is not int for x in (start,end,observed,pid)) or not 0<start<end<=observed or end-start>DAY or pid<=0:
        raise ValueError("window")
    if not isinstance(rows,list) or len(rows)>4000:raise ValueError("row_count")
    rows=unique(rows)
    if any(type(r["at_us"]) is not int or not start<=r["at_us"]<=end for r in rows):raise ValueError("posting_scope")
    unknown=sum(r["asset"]!="USD" or r["product_id"] not in (None,str(pid)) or r["type"] not in CAPITAL_TYPES|POSTED_TYPES for r in rows)
    payload=dict(symbol=s,binding=binding,start=start,end=end,observed=observed,product_id=pid,postings=rows)
    body=canonical(payload);h=digest(payload)
    p=Path(path)
    fd=os.open(p,os.O_CREAT|os.O_NOFOLLOW|os.O_RDWR,0o600)
    try:
        st=os.fstat(fd)
        if st.st_uid!=os.geteuid() or st.st_mode&0o077 or st.st_nlink!=1:raise ValueError("private_archive")
    finally:os.close(fd)
    with closing(sqlite3.connect(p,timeout=5)) as db,db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE IF NOT EXISTS windows(symbol TEXT,binding TEXT,observed INTEGER,start INTEGER,end INTEGER,body TEXT,sha TEXT,PRIMARY KEY(symbol,observed))")
        db.execute("CREATE TABLE IF NOT EXISTS posting_versions(symbol TEXT,binding TEXT,id TEXT,sha TEXT,body TEXT,PRIMARY KEY(symbol,id,sha))")
        for table in ("windows","posting_versions"):
            for op in ("UPDATE","DELETE"):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable evidence'); END")
        db.execute("BEGIN IMMEDIATE")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        if db.execute("SELECT 1 FROM windows WHERE (symbol=? AND binding<>?) OR (symbol<>? AND binding=?) LIMIT 1",(s,binding,s,binding)).fetchone():raise ValueError("account_changed")
        last=db.execute("SELECT observed,sha FROM windows WHERE symbol=? ORDER BY observed DESC LIMIT 1",(s,)).fetchone()
        if last and observed<=last[0]:
            if observed!=last[0] or h!=last[1]:raise ValueError("nonmonotonic_query")
        else:
            db.execute("INSERT INTO windows VALUES(?,?,?,?,?,?,?)",(s,binding,observed,start,end,body,h))
            for r in rows:
                db.execute("INSERT OR IGNORE INTO posting_versions VALUES(?,?,?,?,?)",(s,binding,r["id"],digest(r),canonical(r)))
        conflicts=db.execute("SELECT count(*) FROM (SELECT id FROM posting_versions WHERE symbol=? GROUP BY id HAVING count(*)>1)",(s,)).fetchone()[0]
        count=db.execute("SELECT count(*) FROM windows WHERE symbol=?",(s,)).fetchone()[0]
    return dict(status="query_archived",query_count=count,posting_count=len(rows),
                unclassified_count=unknown,conflicting_posting_ids=conflicts,
                broker_finality_verified=False,continuous_coverage_verified=False,
                historical_loss_reconciled=False,execution_authorized=False)

def collect(root,children,parent,*,clock=None):
    from datetime import datetime,timezone
    from tradebot.m31_equity_evidence_v3 import sample
    from tradebot.equity_receipt import validate_receipt
    from tradebot.owner_connectivity_bridge_v3 import AccountReader
    from tradebot.signed_margin_mode import _user_id
    from tradebot.fire_reconciliation import normalize_posting
    from tradebot.research_collector_v3 import atomic_json
    from tradebot.portfolio_equity_guard import stamp
    import hashlib
    clock=clock or (lambda:datetime.now(timezone.utc))
    root=Path(root);p=root/"m31-equity-evidence-v3.sqlite"
    out=dict(mode="rolling_cashflow_archive_only",markets={},execution_authorized=False,orders_submitted=0,policy_changed=False)
    for s in LABELS:
        try:
            if not p.is_file() or p.is_symlink():raise ValueError("equity_archive")
            with closing(sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
                db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
                if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
                verified=[]
                for order in ("ASC","DESC"):
                    binding,t,body,h=db.execute("SELECT binding,stamp,body,sha FROM observations WHERE symbol=? ORDER BY stamp "+order+" LIMIT 1",(s,)).fetchone()
                    r=json.loads(body)
                    if digest(r)!=h or (r["symbol"],r["account_binding"],r["observed_us"])!=(s,binding,t) or r["receipt"]["received_us"]!=t:raise ValueError("scope")
                    validate_receipt(r["equity_usd"],r["receipt"],now=datetime.fromtimestamp(t/1e6,timezone.utc))
                    verified.append(r)
            a,b=verified
            if a["account_binding"]!=b["account_binding"] or not 0<=stamp(clock())-b["observed_us"]<=180000000:raise ValueError("stale_archive")
            c=children[s];current=sample(s,c,parent,clock)
            if current["account_binding"]!=b["account_binding"]:raise ValueError("identity")
            reader=AccountReader(c,s)
            product=reader._request("GET","/v2/products/"+s)["result"]
            if product["symbol"]!=s or type(product["id"]) is not int:raise ValueError("product")
            end=b["observed_us"];start=max(a["observed_us"],end-DAY)
            if start>=end:raise ValueError("window")
            raw=c.wallet_postings(start,end)
            prefs=reader._request("GET","/v2/users/trading_preferences",auth=True)["result"]
            if hashlib.sha256(("delta-demo:"+_user_id(prefs["user_id"])).encode()).hexdigest()!=b["account_binding"]:raise ValueError("identity_changed")
            r=record(root/"m33-cashflow-archive-v3.sqlite",s,b["account_binding"],start,end,stamp(clock()),[normalize_posting(x) for x in raw],product["id"])
            r.update(window_start_us=start,window_end_us=end)
        except Exception as e:r=dict(status="unavailable",reason=type(e).__name__,execution_authorized=False)
        out["markets"][s]=r
    out["checked_at"]=int(clock().timestamp())
    atomic_json(root/"m33-cashflow-archive-v3.json",out)
    return out
