"""Read-only BTCUSD autonomous DEMO admission diagnostic.

Never arms the agent, sends an order, invokes GPT or changes durable receipts.
This is advisory evidence only; execution rechecks all broker/risk gates.
"""
import argparse
import json
from pathlib import Path

from tradebot.btc_autonomous_demo import is_armed, prior_fire_receipts_safe
from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.fire_btc_supervised_commission import readonly_btc_commission_preflight


def inspect(data_dir, *, broker_factory=DeltaDemo,
            preflight=readonly_btc_commission_preflight,
            armed=is_armed, receipts_safe=prior_fire_receipts_safe):
    root = Path(data_dir)
    result = {
        "environment": "delta-india-demo",
        "mode": "read_only_unattended_readiness",
        "status": "blocked",
        "blockers": [],
        "operator_arm_present": False,
        "previous_fire_receipts_safe": False,
        "demo_broker_preflight_verified": False,
        "owner_margin_attestation_is_broker_proof": False,
        "order_authorized": False,
        "broker_mutations": False,
        "ai_calls": 0,
    }
    blockers = result["blockers"]
    if root.is_symlink() or not root.is_dir():
        blockers.append("trusted_data_directory_missing")
        return result
    try:
        result["operator_arm_present"] = armed() is True
    except Exception:
        pass
    if not result["operator_arm_present"]:
        blockers.append("owner_autonomous_arm_missing")
    # Fail closed on HALT regardless of receipt state or broker preflight.
    if (root / "btc-auto-demo-halt").exists():
        blockers.append("unattended_halt_requires_operator_review")
    try:
        result["previous_fire_receipts_safe"] = receipts_safe(root) is True
    except Exception:
        pass
    if not result["previous_fire_receipts_safe"]:
        blockers.append("previous_fire_requires_operator_review")
    try:
        broker = broker_factory(allow_orders=False)
        if (getattr(broker, "base_url", None) != DEMO_API
                or getattr(broker, "allow_orders", None) is not False):
            blockers.append("readonly_delta_demo_client_required")
        else:
            check = preflight(broker, root)
            if type(check) is dict:
                ok = (check.get("status") == "operator_review_candidate_only"
                      and check.get("blockers") == []
                      and check.get("supervised_session_verified") is True
                      and check.get("recent_btc_history_local_quality_verified") is True
                      and check.get("owner_declared_main_isolated_accepted") is True
                      and check.get("account_wide_flatness_verified") is True
                      and check.get("watchdog_and_collector_active") is True
                      and check.get("both_dashboard_fire_endpoints_disabled") is True
                      and check.get("signed_isolated_margin_verified") is False
                      and check.get("trade_authorized") is False)
                result["demo_broker_preflight_verified"] = bool(ok)
                if not ok:
                    safe_names = {
                        "fresh_session_equity_unverified",
                        "restricted_btc_recent24h_history_unverified",
                        "owner_main_isolated_declaration_missing_or_expired",
                        "account_wide_exposure_unverified",
                        "independent_protection_services_unverified",
                        "existing_dashboard_fire_not_disabled_or_unavailable",
                        "readonly_delta_demo_client_required",
                    }
                    for value in check.get("blockers") or []:
                        if type(value) is str and value in safe_names:
                            blockers.append(value)
                    if not check.get("blockers"):
                        blockers.append("broker_preflight_evidence_incomplete")
            else:
                blockers.append("broker_preflight_unavailable")
    except Exception:
        # Do not expose upstream errors, response bodies or credentials.
        blockers.append("broker_preflight_unavailable")
    result["blockers"] = sorted(set(blockers))
    result["status"] = "eligible_read_only_no_order" if not result["blockers"] else "blocked"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)
    print(json.dumps(inspect(args.data_dir), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
