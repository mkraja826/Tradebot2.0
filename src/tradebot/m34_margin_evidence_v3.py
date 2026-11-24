"""Signed margin-setting evidence only, not a broker preflight or order permit."""
from pathlib import Path
from datetime import datetime,timezone
from tradebot.m23_execution_account_v3 import inspect
from tradebot.research_collector_v3 import atomic_json
from tradebot.signed_account_context_v3 import LABELS

def project(a):
    out=dict(status="unresolved",execution_authorized=False,
             actual_order_margin_verified=False,account_maximum_leverage_verified=False,
             broker_pretrade_quote_available=False,
             existing_blocked_margin_is_new_order_quote=False)
    l=a.get("leverage_evidence",{})
    if (a.get("status")!="signed_readonly_exposure_verified" or a.get("identity_verified") is not True
        or a.get("flat_exposure_verified") is not True or a.get("execution_authorized") is not False
        or l.get("status")!="signed_setting_observed" or l.get("execution_authorized") is not False):
        return out
    return dict(out,status="signed_existing_margin_setting_observed",
                configured_leverage=l["configured_leverage"],
                blocked_order_margin_zero=l["blocked_order_margin_zero"],
                within_existing_20x_ceiling=l["within_existing_20x_ceiling"],
                order_mutation_permission_verified=False)

def collect(root,children,parent,*,clock=lambda:datetime.now(timezone.utc)):
    out=dict(mode="margin_setting_evidence_only",markets={},execution_authorized=False,
             orders_submitted=0,policy_changed=False)
    for s in LABELS:out["markets"][s]=project(inspect(s,children[s],parent,clock=clock))
    out["checked_at"]=int(clock().timestamp())
    atomic_json(Path(root)/"m34-margin-evidence-v3.json",out)
    return out
