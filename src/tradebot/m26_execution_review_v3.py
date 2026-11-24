"""Review-only consolidation of execution prerequisites. No admission API."""
from datetime import datetime,timezone
from pathlib import Path
from time import time
import json
from tradebot.m20_subaccount_baseline_v3 import read_private
from tradebot.deployment_readiness_v3 import checkpoint,checkpoint_status
from tradebot.equity_checkpoint_health import checkpoint_health
from tradebot.research_collector_v3 import atomic_json

def project(symbol,account,legacy,child,*,now):
    if symbol not in ("BTCUSD","XAUTUSD"):raise ValueError("invalid_market")
    a={}
    try:
        t=datetime.fromisoformat(account["markets"][symbol]["observed_at"])
        if (account.get("mode")=="execution_account_diagnostic_only"
            and account.get("execution_authorized") is False
            and type(account.get("orders_submitted")) is int
            and account["orders_submitted"]==0
            and type(account.get("checked_at")) is int
            and 0<=now-account["checked_at"]<=90 and t.tzinfo is not None
            and 0<=now-t.timestamp()<=90):
            a=account["markets"][symbol]
    except (KeyError,ValueError,TypeError,AttributeError):pass
    l=a.get("leverage_evidence",{})
    if not isinstance(l,dict): l={}
    identity=a.get("identity_verified") is True
    flat=identity and a.get("flat_exposure_verified") is True
    checks={
        "account_identity":"observed" if identity else "unverified",
        "account_flatness":"observed" if flat else "unverified",
        "configured_leverage":"observed_within_existing_ceiling" if flat and l.get("within_existing_20x_ceiling") is True else "unverified_or_outside_ceiling",
        "execution_permission":"uncommissioned",
        "actual_order_margin":"uncommissioned",
        "decision_validation":"requires_current_trade",
        "protective_order_verification":"requires_actual_fill",
        "order_lifecycle":"broker_commissioning_pending",
        "independent_equity_policy":"review_pending",
        "existing_equity_release":"blocked" if legacy.get("prerequisites_met") is False else "unverified_or_observed_not_authority",
        "child_daily_checkpoint":child.get("daily_checkpoint","unavailable"),
        "child_weekly_checkpoint":child.get("weekly_checkpoint","unavailable"),
    }
    return dict(symbol=symbol,checks=checks,existing_release_blockers=legacy.get("blocking_conditions",[]) or (["checkpoint_unverified"] if legacy.get("prerequisites_met") is None else []),
                execution_authorized=False,orders_submitted=0,policy_deployed=False)

def collect(root,*,legacy_root=Path("/home/support/Tradebot2.0/data")):
    root=Path(root);now=time()
    try:a=json.loads(read_private(root/"m23-execution-account-v3.json"))
    except (ValueError,OSError):a={}
    try:
        raw=checkpoint();now=time();legacy=checkpoint_status(raw,now)
    except Exception:legacy={"prerequisites_met":None,"blocking_conditions":["checkpoint_unavailable"]}
    out=dict(mode="execution_gate_review_only",checked_at=int(now),markets={},
             execution_authorized=False,orders_submitted=0,paid_ai_requests=0,
             existing_policy_changed=False,policy_deployed=False)
    for s,d in (("BTCUSD","btc-isolated"),("XAUTUSD","gold-isolated")):
        h=checkpoint_health(legacy_root/d/"fire-equity-risk.sqlite",at=datetime.fromtimestamp(now,timezone.utc))
        out["markets"][s]=project(s,a,legacy,h,now=now)
    atomic_json(root/"m26-execution-review-v3.json",out)
    return out
