"""Read-only recovery diagnostics; no automatic retry, flatten or release."""
from datetime import datetime
from pathlib import Path
from time import time
from contextlib import closing
import json,sqlite3
from tradebot.m20_subaccount_baseline_v3 import read_private
from tradebot.demo_upgrade_preflight import _receipt_states
from tradebot.research_collector_v3 import atomic_json

def project(s,account,monitor,unresolved,*,now):
    alerts=[]
    a=account.get("markets",{}).get(s,{})
    m=monitor.get("markets",{}).get(s,{}).get("current",{})
    def fresh(r,mode):
        t=r.get("checked_at")
        return r.get("mode")==mode and r.get("execution_authorized") is False and type(t) is int and 0<=now-t<=90
    flat=False
    if fresh(account,"execution_account_diagnostic_only"):
        try:
            t=datetime.fromisoformat(a["observed_at"])
            flat=t.tzinfo is not None and 0<=now-t.timestamp()<=90 and a.get("identity_verified") is True and a.get("flat_exposure_verified") is True
        except (KeyError,ValueError,TypeError):pass
    if not flat:alerts.append("direct_flatness_not_verified")
    status="unavailable"
    if fresh(monitor,"read_only_position_monitor") and m.get("symbol")==s:
        status=m.get("status","unavailable")
        if status!="unknown":
            t=m.get("observed_us")
            if type(t) is not int or not 0<=now-t/1e6<=60:status="stale"
    if status!="flat_observed":alerts.append("monitor_"+status if status in ("unknown","unavailable","stale","open_protection_unverified","open_protection_reported","flat_orders_present") else "monitor_invalid")
    # Independent snapshots can legitimately differ in time. Do not infer
    # missing protection or confirmed flatness from conflicting observations.
    conflict=flat and status in ("open_protection_unverified","open_protection_reported","flat_orders_present")
    if conflict:alerts.append("inventory_observations_disagree")
    if conflict:exposure_state="conflicting_observations"
    elif flat and status=="flat_observed":exposure_state="flat_corroborated"
    elif status in ("open_protection_unverified","open_protection_reported"):exposure_state="open_reported"
    elif status=="flat_orders_present":exposure_state="orders_reported"
    else:exposure_state="unresolved"
    if type(unresolved) is not int or unresolved<0:alerts.append("receipt_audit_unavailable")
    elif unresolved:alerts.append("unresolved_order_receipts")
    return dict(symbol=s,direct_flatness_observed=flat,monitor_status=status,
                unresolved_receipts=unresolved,alerts=alerts,exposure_state=exposure_state,settlement_verified=False,
                restart_recovery_commissioned=False,emergency_transport_commissioned=False,
                execution_authorized=False,retry_authorized=False,orders_submitted=0)

def collect(root,*,legacy_root=Path("/home/support/Tradebot2.0/data")):
    root=Path(root)
    def load(name):
        try:return json.loads(read_private(root/name))
        except (OSError,ValueError):return {}
    a=load("m23-execution-account-v3.json")
    m=load("position-monitor-status.json")
    now=time()
    out=dict(mode="recovery_diagnostic_only",checked_at=int(now),markets={},execution_authorized=False,orders_submitted=0)
    for s,d,name in (("BTCUSD","btc-isolated","fire-ops.sqlite"),("XAUTUSD","gold-isolated","fire-xaut.sqlite")):
        try:
            p=legacy_root/d/name
            if not p.is_file() or p.is_symlink():raise ValueError("ledger")
            with closing(sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True)) as db:
                if db.execute("PRAGMA quick_check(1)").fetchone()!=("ok",):raise ValueError("integrity")
            n=_receipt_states(legacy_root/d,s)
        except (OSError,ValueError,sqlite3.Error):n=None
        out["markets"][s]=project(s,a,m,n,now=now)
    atomic_json(root/"m27-recovery-audit-v3.json",out)
    return out
