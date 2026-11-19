"""Fail-closed, deterministic FIRE per-trade risk gate (Delta India Demo).

This is only the per-order subset of the planned portfolio risk governor.
Daily/weekly drawdown, funding, portfolio correlation and accounting gates
remain separate pending broker-backed ledger completion. No LLM can override.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class RiskRejected(ValueError):
    """A proposed demo trade exceeds the independent execution safety policy."""


@dataclass(frozen=True)
class FireRiskLimits:
    equity_risk_fraction: Decimal = Decimal("0.0025")
    max_effective_leverage: Decimal = Decimal("5")
    minimum_net_reward_risk: Decimal = Decimal("1.5")
    slippage_reserve_each_side: Decimal = Decimal("0.0005")
    version: str = "fire-demo-risk-v1"

    def __post_init__(self):
        if (not 0 < self.equity_risk_fraction <= Decimal("0.01")
                or not 0 < self.max_effective_leverage <= Decimal("5")
                or not Decimal("1") <= self.minimum_net_reward_risk
                or not 0 <= self.slippage_reserve_each_side <= Decimal("0.01")):
            raise ValueError("Invalid demo risk policy")


def _amount(raw, *, positive=False):
    try:
        value = Decimal(str(raw))
        if not value.is_finite() or (positive and value <= 0) or value < 0:
            raise ValueError
        return value
    except (TypeError, ValueError, InvalidOperation):
        raise RiskRejected("Missing or invalid verified risk input") from None


def assess_fire_plan(plan, budget, quote, *, limits=None):
    """Verify net risk, target quality and effective leverage BEFORE any POST.

    Assumes vanilla USD-settled linear contracts and the verified contract
    multiplier supplied by entry_budget. The reserve models entry/exit
    slippage and taker commissions; it does NOT guarantee execution at stop.
    """
    limits = limits or FireRiskLimits()
    side, contracts = plan.get("direction"), plan.get("contracts")
    if side not in ("LONG", "SHORT") or type(contracts) is not int or contracts < 1:
        raise RiskRejected("Invalid proposal size or direction")
    if contracts > budget.get("max_contracts_per_entry", -1):
        raise RiskRejected("Above verified margin limit")
    equity = _amount(budget.get("equity_usd"), positive=True)
    multiplier = _amount(budget.get("contract_value"), positive=True)
    fee_rate = _amount(budget.get("taker_commission_rate"))
    if fee_rate > Decimal("0.05"):
        raise RiskRejected("Unexpected broker fee rate")
    entry = _amount(quote.get("best_ask" if side == "LONG" else "best_bid"), positive=True)
    stop = _amount(plan.get("stop_loss"), positive=True)
    target = _amount(plan.get("take_profit"), positive=True)
    if not (stop < entry < target if side == "LONG" else target < entry < stop):
        raise RiskRejected("Invalid stop or target against executable quote")

    qty = multiplier * contracts
    notional = qty * entry
    gross_loss = qty * abs(entry - stop)
    gross_reward = qty * abs(target - entry)
    reserve = 2 * notional * limits.slippage_reserve_each_side
    loss = gross_loss + qty * (entry + stop) * fee_rate + reserve
    reward = gross_reward - qty * (entry + target) * fee_rate - reserve
    if reward <= 0 or loss <= 0:
        raise RiskRejected("Non-positive net reward or invalid risk")
    maximum_loss = equity * limits.equity_risk_fraction
    leverage = notional / equity
    ratio = reward / loss
    if loss > maximum_loss:
        raise RiskRejected("Stop-loss exposure exceeds equity risk limit")
    if leverage > limits.max_effective_leverage:
        raise RiskRejected("Effective leverage exceeds policy")
    if ratio < limits.minimum_net_reward_risk:
        raise RiskRejected("Expected net reward-to-risk below policy")
    return {
        "policy_version": limits.version,
        "equity_usd": str(equity),
        "notional_usd": str(notional),
        "estimated_loss_including_costs_usd": str(loss),
        "estimated_net_target_reward_usd": str(reward),
        "max_allowed_loss_usd": str(maximum_loss),
        "expected_net_reward_risk": str(ratio),
        "effective_leverage": str(leverage),
        "slippage_assumption_each_side": str(limits.slippage_reserve_each_side),
        "approved": True,
    }
