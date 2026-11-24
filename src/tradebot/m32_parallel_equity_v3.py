"""Scheduled parallel evidence comparison; no risk decision or execution interface."""
from datetime import datetime,timezone
from pathlib import Path
from decimal import Decimal
from tradebot.m31_cashflow_evidence_v3 import collect as cashflows
from tradebot.m31_loss_observations_v3 import collect as losses
from tradebot.equity_checkpoint_health import checkpoint_health
from tradebot.portfolio_equity_guard import DEFAULT_LIMITS
from tradebot.research_collector_v3 import atomic_json

def project(new,legacy):
    out=dict(candidate_status=new.get("status","unavailable"),
        legacy_daily=legacy.get("daily_checkpoint","unavailable"),
        legacy_weekly=legacy.get("weekly_checkpoint","unavailable"),
        legacy_blocking_conditions=legacy.get("blocking_conditions",[]),
        historical_equivalence_verified=False,execution_authorized=False,
        comparison_scope="different_historical_windows_not_equivalent")
    checks={}
    for name,key,limit in zip(("daily","weekly","sampled_peak"),
            ("daily_observed_decline","weekly_observed_decline","sampled_archive_peak_decline"),DEFAULT_LIMITS):
        value=new.get(key)
        state="unresolved"
        if new.get("status")=="observed_raw_declines_only" and value is not None and new.get("gaps_over_180s")==0:
            d=Decimal(value)
            if d.is_finite() and 0<=d<=1:
                state="observed_decline_at_or_above_reference" if d>=Decimal(str(limit)) else "observed_decline_below_reference"
        checks[name]=dict(observation=value,reference_limit=str(limit),status=state)
    out["diagnostic_comparisons"]=checks
    return out

def collect(root,children,parent,*,clock=lambda:datetime.now(timezone.utc),
            legacy_root=Path("/home/support/Tradebot2.0/data")):
    root=Path(root)
    cashflows(root,children,parent,clock=clock)
    new=losses(root,clock=clock)
    now=clock()
    out=dict(mode="parallel_equity_diagnostics_only",checked_at=int(now.timestamp()),
             markets={},execution_authorized=False,orders_submitted=0,policy_changed=False,
             continuous_production_policy_verified=False)
    for s,d in (("BTCUSD","btc-isolated"),("XAUTUSD","gold-isolated")):
        try:
            old=checkpoint_health(legacy_root/d/"fire-equity-risk.sqlite",at=now)
            out["markets"][s]=project(new["markets"][s],old)
        except Exception as e:
            out["markets"][s]=dict(candidate_status="unavailable",reason=type(e).__name__,execution_authorized=False)
    atomic_json(root/"m32-parallel-equity-v3.json",out)
    return out
