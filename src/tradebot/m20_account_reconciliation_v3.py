"""Read-only comparison of new monitoring and existing execution prerequisites."""
from pathlib import Path
from time import time
from tradebot.dashboard_context_v3 import read_accounts
from tradebot.deployment_readiness_v3 import checkpoint,checkpoint_status
from tradebot.owner_connectivity_bridge_v3 import read_report
from tradebot.model_wire_v3 import MODEL_IDS
from tradebot.research_collector_v3 import atomic_json

def project(owner,legacy,risk,*,now):
    out={"mode":"account_monitor_reconciliation_only","checked_at":now,
         "legacy_checkpoint":risk,"markets":{},"execution_authorized":False,
         "orders_submitted":0,"paid_ai_requests":0}
    for s in MODEL_IDS:
        a=owner.get("markets",{}).get(s,{})
        b=legacy.get(s,{})
        fresh=owner.get("status")=="fresh_local_report" and a.get("account_evidence_fresh") is True
        signed=b.get("signed_account_verified") is True
        halted=b.get("halted")
        blockers=[]
        if not fresh:blockers.append("new_account_evidence_unavailable")
        if not signed:blockers.append("legacy_account_unverified")
        if halted is not False:blockers.append("halt_active_or_unknown")
        if risk.get("prerequisites_met") is not True:blockers.append("legacy_checkpoint_unmet_or_unknown")
        blockers.extend(("actual_order_margin_unverified","account_maximum_leverage_unverified","broker_execution_uncommissioned"))
        out["markets"][s]={"new_monitor_fresh":fresh,"legacy_account_verified":signed,
           "legacy_halted":halted,"connection_discrepancy":fresh and not signed,
           "checkpoint_scope":"legacy_not_account_specific","blockers":blockers,
           "autonomous_trading_ready":False}
    return out

def tick(root,*,clock=time,owner_reader=read_report,legacy_reader=read_accounts,risk_reader=checkpoint):
    root=Path(root)
    try:legacy=legacy_reader()
    except Exception:legacy={}
    try:raw=risk_reader()
    except Exception:raw={}
    instant=clock();now=int(instant)
    risk=checkpoint_status(raw,instant)
    out=project(owner_reader(root,now=now),legacy,risk,now=now)
    atomic_json(root/"m20-account-reconciliation-v3.json",out)
    return out
