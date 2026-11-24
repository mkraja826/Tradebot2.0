"""Read-only Gold isolated DEMO autonomous admission evidence.

Model calls, ledger modifications, and broker mutations are prohibited here.
"""
from pathlib import Path
import os
import subprocess

from tradebot.btc_supervised_session import inspect_btc_session_candidate
from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.fire_account_guard import require_flat_demo_account_for_configuration
from tradebot.fire_commission_preflight import _fire_disabled
from tradebot.gold_recent24h import inspect_recent_gold_window
from tradebot.signed_margin_mode import signed_account_margin_mode


def _gold_services_active():
    services = (
        "tradebot2-isolated-demo-monitor@GOLD-watchdog.service",
        "tradebot2-isolated-demo-monitor@GOLD-equity.service",
        "tradebot2-isolated-telegram@GOLD.service",
        "tradebot2-dashboard.service",
    )
    return all(subprocess.run(
        ["systemctl", "is-active", "--quiet", service],
        timeout=3,check=False).returncode == 0 for service in services)


def gold_preflight(root, *, broker_factory=DeltaDemo,
                   session=inspect_btc_session_candidate,
                   market=inspect_recent_gold_window,
                   account_flat=require_flat_demo_account_for_configuration,
                   service_check=_gold_services_active, dashboard_off=_fire_disabled):
    root = Path(root)
    report = {
        "status":"blocked",
        "blockers":[],
        "symbol":"XAUTUSD",
        "environment":"delta-india-demo",
        "model":"tb-deepseek-v4-1-flash",
        "signed_isolated_margin":False,
        "account_flat":False,
        "recent_24h_complete":False,
        "fresh_equity":False,
        "services_healthy":False,
        "dashboard_fire_disabled":False,
        "quality_warnings":[],
        "ai_calls":0,"broker_mutations":False,"order_authorized":False,
    }
    blocks=report["blockers"]
    if (os.environ.get("TRADEBOT_EXPECTED_DEMO_SUBACCOUNT") != "GOLD"
            or root.name != "gold-isolated"
            or root.is_symlink() or root.parent.is_symlink()
            or not root.is_dir()):
        blocks.append("gold_isolated_private_scope_invalid")
        return report
    try:
        report["services_healthy"]=service_check() is True
        if not report["services_healthy"]:
            blocks.append("gold_watchdog_equity_alerts_or_dashboard_not_ready")
    except Exception:
        blocks.append("gold_service_verification_unavailable")
    try:
        report["dashboard_fire_disabled"]=dashboard_off() is True
        if not report["dashboard_fire_disabled"]:
            blocks.append("dashboard_fire_order_endpoints_enabled_or_unavailable")
    except Exception:
        blocks.append("dashboard_fire_order_endpoint_state_unavailable")
    try:
        broker=broker_factory(api_key=os.getenv("DELTA_DEMO_API_KEY",""),
                              api_secret=os.getenv("DELTA_DEMO_API_SECRET",""),
                              allow_orders=False)
        if broker.base_url != DEMO_API or broker.allow_orders is not False:
            blocks.append("readonly_delta_demo_broker_required")
            return report
    except Exception:
        blocks.append("gold_readonly_broker_unavailable")
        return report
    try:
        report["signed_isolated_margin"]=signed_account_margin_mode(broker)=="isolated"
        if not report["signed_isolated_margin"]:
            blocks.append("gold_signed_isolated_margin_unavailable")
    except Exception:
        blocks.append("gold_signed_isolated_margin_unavailable")
    try:
        flat=account_flat(broker)
        report["account_flat"]=flat.get("account_flat_verified") is True
        if not report["account_flat"]:
            blocks.append("gold_account_wide_flatness_unverified")
    except Exception:
        blocks.append("gold_account_wide_flatness_unverified")
    try:
        history=market(root.parent)
        report["recent_24h_complete"]=(
            history.get("status")=="recent24h_local_candidate_only"
            and history.get("symbol")=="XAUTUSD"
            and history.get("complete_contiguous_24h") is True
            and history.get("retained_bars")==288
            and history.get("quarantined_bars")==0
            and history.get("suspect_bars")==0)
        if not report["recent_24h_complete"]:
            blocks.append("gold_recent24h_bars_or_integrity_unavailable")
    except Exception:
        blocks.append("gold_recent24h_bars_or_integrity_unavailable")
    try:
        equity=session(broker,root,allow_daily_loss_warning=True,
            allow_portfolio_loss_warnings=True,
            allow_initial_isolated_genesis=True,
            isolated_genesis_account="GOLD",
            expected_market_symbol="XAUTUSD")
        report["fresh_equity"]=(
            equity.get("status")=="baseline_candidate_review_only"
            and equity.get("session_budget_within_limits") is True
            and equity.get("fresh_session_wallet_baseline_verified") is True
            and equity.get("original_equity_history_integrity_verified") is True
            and equity.get("watchdog_and_collector_healthy") is True
            and equity.get("trade_authorized") is False)
        report["quality_warnings"]=[
            w for w in equity.get("quality_warnings",[])
            if type(w) is str][:10]
        if not report["fresh_equity"]:
            blocks.append("gold_signed_session_equity_unverified")
    except Exception:
        blocks.append("gold_signed_session_equity_unverified")
    if not blocks:
        report["status"]="eligible_read_only_no_order"
    return report


def inspect(root, *, preflight=gold_preflight):
    from tradebot.gold_autonomous_demo import is_gold_armed, receipts_safe
    result=preflight(root)
    blocks=result["blockers"]
    try:
        if receipts_safe(root) is not True:
            blocks.append("previous_gold_fire_needs_review")
    except Exception:
        blocks.append("previous_gold_fire_needs_review")
    try:
        result["armed"]=is_gold_armed() is True
    except Exception:
        result["armed"]=False
    if not result["armed"]:
        blocks.append("gold_autonomous_arm_missing")
    try:
        if (Path(root)/"gold-auto-demo-halt").exists():
            blocks.append("gold_isolated_halt_requires_review")
    except OSError:
        blocks.append("gold_isolated_halt_state_unavailable")
    if blocks:result["status"]="blocked"
    return result


def main(argv=None):
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",default="data/gold-isolated")
    args=parser.parse_args(argv)
    print(json.dumps(inspect(args.data_dir),sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
