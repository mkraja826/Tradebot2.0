"""Read-only historical equity/capital comparison; never a release gate."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from contextlib import closing
from decimal import Decimal
import sqlite3,json
from tradebot.delta import DEMO_API
from tradebot.equity_checkpoint_health import checkpoint_health
from tradebot.equity_receipt import validate_receipt
from tradebot.portfolio_equity_guard import stamp,amount,validated_watermark,ANCHOR_WINDOW
from tradebot.m20_subaccount_equity_v3 import CAPITAL_TYPES,number
from tradebot.isolated_performance import POSTED_TYPES
from tradebot.fire_reconciliation import normalize_posting,unique
from tradebot.research_collector_v3 import atomic_json

def snapshots(path,now):
    if path.is_symlink() or not path.is_file():raise ValueError("ledger_unavailable")
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("BEGIN")
        if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
        peak=validated_watermark(db);t=stamp(now)
        current=db.execute("SELECT observed_us,equity_usd FROM equity_evidence ORDER BY observed_us DESC LIMIT 1").fetchone()
        if not 0<=t-current[0]<=180000000:raise ValueError("stale")
        day=now.astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
        anchors={}
        for k,start in (("daily",day),("weekly",day-timedelta(days=day.weekday()))):
            a=stamp(start)
            anchors[k]=db.execute("SELECT observed_us,equity_usd FROM equity_evidence WHERE observed_us>=? AND observed_us<? AND observed_us<=? ORDER BY observed_us LIMIT 1",(a,a+ANCHOR_WINDOW*1000000,t)).fetchone()
        anchors["peak"]=next((r for r in db.execute("SELECT observed_us,equity_usd FROM equity_evidence ORDER BY observed_us DESC") if amount(r[1])==peak),None)
        for row in [current,*anchors.values()]:
            if row is None:continue
            saved=db.execute("SELECT receipt FROM equity_read_receipts WHERE observed_us=?",(row[0],)).fetchone()
            at=datetime.fromtimestamp(row[0]/1000000,timezone.utc)
            if not saved or stamp(validate_receipt(row[1],json.loads(saved[0]),now=at))!=row[0]:raise ValueError("unverified_receipt")
        return current,anchors

def compare(opening,closing,rows):
    a,b=amount(opening[1]),amount(closing[1])
    start,end=opening[0],closing[0]
    if not 0<end-start<=7*86400*1000000:raise ValueError("unsupported_window")
    cap=Decimal(0);trade=Decimal(0);counts=dict(capital=0,transfers=0,trading=0,unclassified=0)
    for p in unique(rows):
        if not start<p["at_us"]<=end:raise ValueError("window_mismatch")
        if p["asset"]!="USD":counts["unclassified"]+=1
        elif p["type"] in CAPITAL_TYPES:
            cap+=number(p["amount"]);counts["capital"]+=1
            counts["transfers"]+=p["type"]=="sub_account_transfer"
        elif p["type"] in POSTED_TYPES:
            trade+=number(p["amount"]);counts["trading"]+=1
        else:counts["unclassified"]+=1
    if counts["unclassified"]:return dict(status="unclassified_postings",counts=counts)
    adjusted=b-a-cap
    return dict(status="conditional_comparison",counts=counts,raw_decline=b<a,
                capital_net_outflow=cap<0,adjusted_decline=adjusted<0,
                residual_zero=adjusted-trade==0,
                historical_account_binding_verified=False,verified_return=False)

def collect(root,children,parent,*,legacy_root=Path("/home/support/Tradebot2.0/data"),clock=lambda:datetime.now(timezone.utc)):
    now=clock()
    out=dict(mode="historical_equity_reconciliation_diagnostic_only",checked_at=int(now.timestamp()),accounts={},execution_authorized=False,orders_submitted=0,paid_ai_requests=0,historical_checkpoint_replaced=False,protection_policy_changed=False)
    for name,client,path in (("legacy_parent_candidate",parent,legacy_root),("BTCUSD",children.get("BTCUSD"),legacy_root/"btc-isolated"),("XAUTUSD",children.get("XAUTUSD"),legacy_root/"gold-isolated")):
        ledger=path/"fire-equity-risk.sqlite"
        health=checkpoint_health(ledger,at=now)
        a={k:health[k] for k in ("daily_checkpoint","weekly_checkpoint","latest_receipt_status","database_integrity","observation_status","weekly_next_window_start_utc")}
        a["windows"]={};a["historical_account_binding_verified"]=False
        out["accounts"][name]=a
        try:
            if getattr(client,"base_url",None)!=DEMO_API or getattr(client,"allow_orders",None) is not False:raise ValueError("readonly_required")
            current,anchors=snapshots(ledger,now)
            usable=[r[0] for r in anchors.values() if r is not None and r[0]<current[0]]
            start=min(usable)
            if current[0]-start>7*86400*1000000:raise ValueError("unsupported_history")
            postings=unique([normalize_posting(p) for p in client.wallet_postings(start,current[0])])
            if any(not start<=p["at_us"]<=current[0] for p in postings):raise ValueError("history_outside_window")
            for label,anchor in anchors.items():
                if anchor is None:a["windows"][label]={"status":"missing_checkpoint"};continue
                if anchor[0]==current[0]:a["windows"][label]={"status":"no_elapsed_window"};continue
                a["windows"][label]=compare(anchor,current,[p for p in postings if anchor[0]<p["at_us"]<=current[0]])
            a["status"]="conditional_history_compared"
        except Exception as e:a.update(status="unavailable",reason=type(e).__name__)
    atomic_json(Path(root)/"m23-equity-reconciliation-v3.json",out)
    return out
