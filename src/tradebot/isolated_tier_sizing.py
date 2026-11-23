"""Model-selected demo tiers: audit 5/20/40% EQUITY AS MARGIN at 20x.

This module does not set contracts, change leverage, submit orders or turn
a model's proposed tier into an execution authorization. All quantities
remain model-selected and independently broker/risk-checked.
"""
from decimal import Decimal, InvalidOperation

FIXED_LEVERAGE = 20
MAX_MARGIN_SHARE = Decimal("0.40")
TIER_FRACTIONS = {"small": Decimal("0.05"),
                  "medium": Decimal("0.20"),
                  "large": Decimal("0.40")}
GOLD_DEMO_CAP = 1200
BTC_DEMO_CAP = 96


def _positive(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None


def size_guideline_evidence(plan, signed_preview, *, account):
    """Describe model's unmodified contract choice versus selected guideline."""
    if account not in ("BTC", "GOLD"):
        raise ValueError("Only isolated demo accounts may use tier guidance")
    contracts = plan.get("contracts")
    if type(contracts) is not int or contracts < 1:
        return {}
    tier = plan.get("size_tier")
    if tier not in (*TIER_FRACTIONS, None):
        return {}
    record = {
        "policy": "isolated-demo-ai-selects-margin-tiers-v2",
        "model_proposed_contracts": contracts,
        "selected_contracts": contracts,
        "model_selected_leverage": plan.get("leverage"),
        "model_selected_size_tier": tier,
        "target_equity_margin_fraction": (
            str(TIER_FRACTIONS[tier]) if tier else None),
        "target_equity_notional_fraction": (
            str(TIER_FRACTIONS[tier] * FIXED_LEVERAGE) if tier else None),
        "quantity_auto_reduced": False,
        "quantity_auto_adjusted": False,
        "tiers_are_guidance_only": True,
        "fixed_leverage_policy": FIXED_LEVERAGE,
        "margin_cap_fraction": str(MAX_MARGIN_SHARE),
    }
    if not isinstance(signed_preview, dict):
        return record
    equity = _positive(signed_preview.get("equity_usd"))
    per_contract = _positive(signed_preview.get("notional_per_contract_usd"))
    if equity and per_contract:
        actual_notional = per_contract * contracts
        record["estimated_notional_usd"] = str(actual_notional)
        record["estimated_equity_notional_fraction"] = str(
            actual_notional / equity)
        record["estimated_initial_margin_at_20x_usd"] = str(
            actual_notional / FIXED_LEVERAGE)
        record["estimated_equity_margin_fraction_at_20x"] = str(
            actual_notional / FIXED_LEVERAGE / equity)
        if tier:
            record["target_margin_usd"] = str(
                equity * TIER_FRACTIONS[tier])
            record["target_notional_usd"] = str(
                equity * TIER_FRACTIONS[tier] * FIXED_LEVERAGE)
        record["whole_contract_minimum_notional_usd"] = str(per_contract)
    return record