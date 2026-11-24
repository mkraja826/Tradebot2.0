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
               "equity_loss_warnings": [], "other_review_conditions": [],
               "trade_authorized": False}
        if (isinstance(child, dict) and child.get("label") == label
                and child.get("symbol") == symbol):
            verified = (child.get("status") == "connected"
                        and child.get("margin_mode") == "isolated_verified"
                        and _fresh(child.get("broker_checked_at"), now))
            row["broker_identity_and_margin_reported"] = verified
            health = child.get("equity_health")
            if isinstance(health, dict):
                codes = sorted(set(_codes(health.get("blocking_conditions"))
                                   + _codes(health.get("alert_codes"))))
                row["equity_conditions"] = codes
                row["equity_loss_warnings"] = sorted(set(codes) & LOSS_CODES)
                row["other_review_conditions"] = sorted(set(codes) - LOSS_CODES)
                row["checkpoint_prerequisites_met"] = (
                    health.get("checkpoint_prerequisites_met") is True)
            if not verified:
                row["other_review_conditions"].append("child_broker_evidence_unverified")
        accounts[label] = row
    return {"environment": "delta-india-demo", "mode": "read_only_subaccount_equity",
            "accounts": accounts, "parent_account_scope": "separate_accounting",
            "parent_checkpoint_evaluated_here": False,
            "execution_policy_changed": False, "trade_authorized": False,
            "ready_for_unattended_trading": False}
