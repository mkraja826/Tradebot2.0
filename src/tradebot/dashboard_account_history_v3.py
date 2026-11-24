"""Bounded prospective account chart data, isolated from execution."""
import hashlib,json,sqlite3,time
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from contextlib import closing
from tradebot.m20_subaccount_baseline_v3 import read_private,TARGET
from tradebot.decision_experience_v3 import ro
from tradebot.signed_account_context_v3 import LABELS
from tradebot.opportunity_journal_v3 import canonical

NAME="dashboard-account-history-v3.sqlite"
def number(v):
    if isinstance(v,bool):raise ValueError("invalid_amount")
    d=Decimal(str(v))
    if not d.is_finite() or abs(d)>Decimal("1e15"):raise ValueError("invalid_amount")
    return d
def project(raw,braw,now):
    r=json.loads(raw);b=json.loads(braw)
    if r["mode"]!="subaccount_performance_monitor_only" or r["execution_authorized"] is not False or r["parent_equity_included"] is not False or r["orders_submitted"]!=0 or r["paid_ai_requests"]!=0 or not 0<=now-r["checked_at"]<=660:raise ValueError("invalid_report")
    if hashlib.sha256(braw).hexdigest()!=r["baseline_sha256"] or b["mode"]!="forward_subaccount_baseline_diagnostic_only" or b["execution_authorized"] is not False:raise ValueError("baseline_mismatch")
    out=[]
    for s,label in LABELS.items():
        a=r["markets"][s];base=b["markets"][s]
        if a.get("status")!="offline_calculated" or a.get("current_identity_verified") is not True or a.get("wallet_receipt_verified") is not True or a.get("history_window_complete") is not True:continue
        if a["subaccount"]!=label or a["symbol"]!=s or a["baseline_at"]!=base["observed_at"]:raise ValueError("scope_mismatch")
        t=datetime.fromisoformat(a["observed_at"]);start=datetime.fromisoformat(base["observed_at"])
        if t.tzinfo is None or start.tzinfo is None or not start.timestamp()<t.timestamp()<=now or now-t.timestamp()>660:raise ValueError("invalid_time")
        opening=number(base["opening_equity_usd"]);change=number(a["adjusted_equity_change_usd"]);capital=number(a["net_capital_flow_usd"]);cash=number(a["posted_trading_cashflow_usd"])
        if opening<=0 or opening+change+capital<0:raise ValueError("invalid_equity")
        out.append(dict(symbol=s,at_us=int(t.timestamp()*1000000),baseline_sha256=r["baseline_sha256"],baseline_at=base["observed_at"],equity_usd=str(opening+change+capital),adjusted_equity_usd=str(opening+change),capital_usd=str(capital),posted_cashflow_usd=str(cash)))
    return out
def archive(root,*,now=None):
    root=Path(root);now=time.time() if now is None else now
    rows=project(read_private(root/"m20-subaccount-performance-v3.json"),read_private(root/TARGET),now)
    p=root/NAME
    if p.is_symlink():raise ValueError("untrusted_archive")
    with closing(sqlite3.connect(p,timeout=5)) as db,db:
        db.execute("CREATE TABLE IF NOT EXISTS points(symbol TEXT,at_us INTEGER,baseline TEXT,payload TEXT,PRIMARY KEY(symbol,at_us,baseline))")
        for op in ("UPDATE","DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{op} BEFORE {op} ON points BEGIN SELECT RAISE(ABORT,'immutable point');END")
        for a in rows:
            k=(a["symbol"],a["at_us"],a["baseline_sha256"]);v=canonical(a)
            db.execute("INSERT OR IGNORE INTO points VALUES(?,?,?,?)",(*k,v))
            if db.execute("SELECT payload FROM points WHERE symbol=? AND at_us=? AND baseline=?",k).fetchone()[0]!=v:raise ValueError("point_conflict")
    return len(rows)
def history(root,symbol):
    if symbol not in LABELS:raise ValueError("invalid_symbol")
    root=Path(root);h=hashlib.sha256(read_private(root/TARGET)).hexdigest()
    with closing(ro(root/NAME)) as db:
        rows=db.execute("SELECT payload FROM points WHERE symbol=? AND baseline=? ORDER BY at_us DESC LIMIT 288",(symbol,h)).fetchall()
    return dict(symbol=symbol,points=[json.loads(x[0]) for x in reversed(rows)],scope="prospective_diagnostic_only",execution_authorized=False)

def account_view(root,symbol,*,now=None):
    if symbol not in LABELS:raise ValueError("invalid_symbol")
    root=Path(root);now=time.time() if now is None else now
    out=history(root,symbol)
    out["position"]={"status":"unknown"}
    try:
        raw=read_private(root/"m20-subaccount-performance-v3.json");braw=read_private(root/TARGET)
        r=json.loads(raw);project(raw,braw,now)
        a=r["markets"][symbol];p=a["position_snapshot"]
        at=datetime.fromisoformat(p["observed_at"])
        if a["current_identity_verified"] is not True or a["wallet_receipt_verified"] is not True or p["status"]!="signed_read_only" or p["observed_at"]!=a["observed_at"] or at.tzinfo is None or not 0<=now-at.timestamp()<=360:raise ValueError("stale_position")
        if type(p["open_order_count"]) is not int or not 0<=p["open_order_count"]<=200 or len(p["positions"])>10:raise ValueError("invalid_inventory")
        positions=[]
        for q in p["positions"]:
            if q["symbol"]!=symbol or q["side"] not in ("LONG","SHORT"):raise ValueError("wrong_position")
            item={"side":q["side"]}
            for k in ("size","entry","mark","liquidation","unrealized_pnl"):
                item[k]=None if q.get(k) is None else str(number(q[k]))
            pr=q["protection"];item["protection"]={"status":str(pr["status"])[:50]}
            for k in ("stop_loss","take_profit"):
                item["protection"][k]=None if pr.get(k) is None else str(number(pr[k]))
            positions.append(item)
        out["position"]={"status":"signed_snapshot","observed_at":p["observed_at"],"age_seconds":int(now-at.timestamp()),"open_order_count":p["open_order_count"],"positions":positions}
    except (OSError,ValueError,KeyError,TypeError,AttributeError):pass
    return out

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--directory",required=True)
    args=parser.parse_args();print("observations",archive(args.directory))
