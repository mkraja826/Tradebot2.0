"""Account-scoped DEMO equity diagnostics, never execution authorization.

The parent checkpoint remains a separate accounting record. This module never
substitutes parent data for a missing child, changes ledgers or releases orders.
"""
from datetime import datetime, timezone

MARKETS = {"BTC": "BTCUSD", "GOLD": "XAUTUSD"}
LOSS_CODES = frozenset({"equity_loss_limit_breached",
                        "equity_daily_loss_limit_breached"})
KNOWN_CODES = LOSS_CODES | frozenset({
    "broker_authentication_failed", "broker_equity_unavailable",
    "broker_equity_rejected", "equity_ledger_unavailable",
    "equity_ledger_integrity_failed", "equity_database_integrity_failed",
    "equity_evidence_unavailable", "equity_read_receipt_invalid",
    "equity_receipt_schema_missing", "latest_equity_read_receipt_unverified",
    "signed_equity_observation_stale", "missed_daily_checkpoint",
    "missed_weekly_checkpoint", "watchdog_protection_unverified",
    "watchdog_heartbeat_stale", "equity_collector_heartbeat_stale",
    "operations_evidence_unavailable", "system_clock_unverified",
    "daily_checkpoint_missed_window", "weekly_checkpoint_missed_window",
    "daily_checkpoint_pending_window", "weekly_checkpoint_pending_window",
    "daily_checkpoint_unverified_receipt", "weekly_checkpoint_unverified_receipt",
    "broker_time_evidence_unavailable", "equity_read_receipt_missing",
    "equity_read_value_mismatch", "system_clock_jump", "broker_equity_read_slow",
    "broker_clock_or_stale_response", "broker_equity_response_cached",
    "broker_equity_read_stale", "equity_boundary_ambiguous", "clock_unverified",
    "equity_clock_inconsistent", "operations_clock_inconsistent",
    "watchdog_restart_loop", "equity_collector_restart_loop",
    "watchdog_emergency_flat_verified", "watchdog_protection_failure_flat_verified",
})


def _codes(values):
    if not isinstance(values, list):
        return ["equity_conditions_unavailable"]
    result = set()
    for value in values:
        result.add(value if isinstance(value, str) and value in KNOWN_CODES
                   else "other_equity_condition_requires_review")
    return sorted(result)


def _fresh(timestamp, now, max_age=180):
    try:
        observed = datetime.fromisoformat(timestamp)
        if observed.tzinfo is None:
            return False
        return 0 <= (now - observed).total_seconds() <= max_age
    except (ValueError, TypeError, OverflowError):
        return False


def account_report(overview, *, now=None):
    """Report child-specific evidence; no parent input or permission output."""
    now = now or datetime.now(timezone.utc)
    valid_source = (isinstance(overview, dict)
                    and overview.get("environment") == "delta-india-demo"
                    and overview.get("source") == "isolated_child_accounts"
                    and overview.get("mode") == "read_only")
    source = overview.get("accounts") if valid_source else None
    source = source if isinstance(source, dict) else {}
    accounts = {}
    for label, symbol in MARKETS.items():
        child = source.get(label)
        row = {"symbol": symbol, "account_scope": label,
               "broker_identity_and_margin_reported": False,
               "equity_conditions": ["child_evidence_unavailable"],
               "reported_checkpoint_blockers": ["child_evidence_unavailable"],
               "equity_loss_warnings": [],
               "other_review_conditions": ["child_evidence_unavailable"],
               "checkpoint_prerequisites_met": False,
               "trade_authorized": False}
        if (isinstance(child, dict) and child.get("label") == label
                and child.get("symbol") == symbol):
            verified = (child.get("status") == "connected"
                        and child.get("margin_mode") == "isolated_verified"
                        and _fresh(child.get("broker_checked_at"), now))
            row["broker_identity_and_margin_reported"] = verified
            health = child.get("equity_health")
            if isinstance(health, dict):
                blockers = _codes(health.get("blocking_conditions"))
                alerts = _codes(health.get("alert_codes"))
                review = set()
                if not _fresh(health.get("as_of"), now):
                    review.add("child_equity_report_stale_or_missing")
                if health.get("database_integrity") != "verified":
                    review.add("child_equity_database_unverified")
                if health.get("latest_receipt_status") != "verified":
                    review.add("child_equity_receipt_unverified")
                if health.get("observation_status") != "fresh":
                    review.add("child_equity_observation_unverified")
                for period in ("daily", "weekly"):
                    if health.get(period + "_checkpoint") != "verified":
                        review.add("child_" + period + "_checkpoint_unverified")
                if health.get("checkpoint_prerequisites_met") is not True:
                    review.add("child_checkpoint_prerequisites_unmet")
                codes = set(blockers) | set(alerts) | review
                row["reported_checkpoint_blockers"] = blockers
                row["equity_conditions"] = sorted(codes)
                row["equity_loss_warnings"] = sorted(codes & LOSS_CODES)
                row["other_review_conditions"] = sorted(codes - LOSS_CODES)
                row["checkpoint_prerequisites_met"] = not codes and verified
            if not verified:
                row["other_review_conditions"] = sorted(set(
                    row["other_review_conditions"]) | {"child_broker_evidence_unverified"})
        accounts[label] = row
    return {"environment": "delta-india-demo", "mode": "read_only_subaccount_equity",
            "accounts": accounts, "parent_account_scope": "separate_accounting",
            "parent_checkpoint_evaluated_here": False,
            "execution_policy_changed": False, "trade_authorized": False,
            "ready_for_unattended_trading": False}
