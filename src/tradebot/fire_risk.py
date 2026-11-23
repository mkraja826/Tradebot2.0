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
    equity_risk_fraction: Decimal | None = Decimal("0.0025")
    max_effective_leverage: Decimal = Decimal("20")
    minimum_net_reward_risk: Decimal | None = Decimal("1.5")
    # An additional gross exit-distance rule; independent of fee-adjusted
    # discretionary quality warnings and checked against executable quote.
    minimum_gross_reward_risk: Decimal | None = None
    slippage_reserve_each_side: Decimal = Decimal("0.0005")
    version: str = "fire-demo-risk-v2-dynamic-leverage"
    max_contracts: int = 1

    def __post_init__(self):
        # Discretionary risk/R:R thresholds are warnings-only only for
        # explicitly named, contract-capped isolated BTC/Gold DEMO policies.
        # Broker affordability, effective leverage, liquidation cushion,
        # position/price validity and exact protective orders still gate.
        warning_only_versions = frozenset((
            "btc-demo-chart-stop-v4", "gold-demo-chart-stop-v1"))
        uncapped_demo = (self.equity_risk_fraction is None
                         and self.version in warning_only_versions
                         and self.max_contracts == 6)
        valid_risk_fraction = (
            uncapped_demo or (
                isinstance(self.equity_risk_fraction, Decimal)
                and Decimal("0") < self.equity_risk_fraction <= Decimal("0.01")))
        if (type(self.max_contracts) is not int or not 1 <= self.max_contracts <= 6
                or not valid_risk_fraction
                or not 0 < self.max_effective_leverage <= Decimal("20")
                or not ((self.minimum_net_reward_risk is None and uncapped_demo)
                        or (isinstance(self.minimum_net_reward_risk, Decimal)
                            and Decimal("1") <= self.minimum_net_reward_risk))
                or (self.minimum_gross_reward_risk is not None and
                    (not isinstance(self.minimum_gross_reward_risk, Decimal)
                     or not self.minimum_gross_reward_risk.is_finite()
                     or self.minimum_gross_reward_risk < Decimal("1")))
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
    if contracts > limits.max_contracts:
        raise RiskRejected("Proposed size exceeds scoped BTC DEMO quantity policy")
    if contracts > budget.get("max_contracts_per_entry", -1):
        raise RiskRejected("Above verified margin limit")
    leverage_selected = plan.get("leverage")
    if type(leverage_selected) is not int or not 1 <= leverage_selected <= 20:
        raise RiskRejected("GPT-6 proposed leverage outside 1..20")
    if _amount(budget.get("leverage"), positive=True) != leverage_selected:
        raise RiskRejected("Margin budget not calculated for proposed leverage")
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

    # Enforce user-selected distance rule on the actual executable best
    # ask/bid. This is repeated at the final quote recheck before a POST.
    # LONG: SL < ask < TP; SHORT: TP < bid < SL. Gross target distance must
    # not be smaller than stop distance; fees are still shown separately.
    gross_stop_distance = abs(entry - stop)
    gross_target_distance = abs(target - entry)
    if (limits.minimum_gross_reward_risk is not None and
            gross_target_distance <
            gross_stop_distance * limits.minimum_gross_reward_risk):
        raise RiskRejected("Stop distance exceeds allowed reward distance")
    qty = multiplier * contracts
    notional = qty * entry
    gross_loss = qty * abs(entry - stop)
    gross_reward = qty * abs(target - entry)
    reserve = 2 * notional * limits.slippage_reserve_each_side
    loss = gross_loss + qty * (entry + stop) * fee_rate + reserve
    reward = gross_reward - qty * (entry + target) * fee_rate - reserve
    soft_quality_demo = (
        limits.equity_risk_fraction is None
        and limits.minimum_net_reward_risk is None
        and limits.version in (
            "btc-demo-chart-stop-v4", "gold-demo-chart-stop-v1")
        and limits.max_contracts == 6)
    if loss <= 0 or (reward <= 0 and not soft_quality_demo):
        raise RiskRejected("Non-positive net reward or invalid risk")
    maximum_loss = (equity * limits.equity_risk_fraction
                    if limits.equity_risk_fraction is not None else None)
    leverage = notional / equity
    ratio = reward / loss
    if maximum_loss is not None and loss > maximum_loss:
        raise RiskRejected("Stop-loss exposure exceeds equity risk limit")
    if leverage > limits.max_effective_leverage:
        raise RiskRejected("Effective leverage exceeds policy")
    # Independent theoretical cushion, NOT a broker liquidation estimate.
    # Reserve 2.5% for maintenance/fees and another 1% beyond the stop.
    stop_fraction = abs(entry - stop) / entry
    if stop_fraction + Decimal("0.035") >= Decimal(1) / leverage_selected:
        raise RiskRejected("Stop too close to theoretical liquidation at selected leverage")
    if (limits.minimum_net_reward_risk is not None
            and ratio < limits.minimum_net_reward_risk):
        raise RiskRejected("Expected net reward-to-risk below policy")
    quality_warnings = []
    if soft_quality_demo and ratio < Decimal("1.5"):
        quality_warnings.append("net_reward_risk_below_1_5")
    if soft_quality_demo and reward <= 0:
        quality_warnings.append("net_target_reward_after_costs_nonpositive")
    return {
        "policy_version": limits.version,
        "selected_leverage": leverage_selected,
        "equity_usd": str(equity),
        "notional_usd": str(notional),
        "estimated_loss_including_costs_usd": str(loss),
        "estimated_net_target_reward_usd": str(reward),
        "max_allowed_loss_usd": str(maximum_loss) if maximum_loss is not None else None,
        "estimated_loss_fraction_of_equity": str(loss / equity),
        "equity_loss_ceiling_enabled": maximum_loss is not None,
        "expected_net_reward_risk": str(ratio),
        "gross_stop_distance": str(gross_stop_distance),
        "gross_target_distance": str(gross_target_distance),
        "minimum_gross_reward_risk": (str(limits.minimum_gross_reward_risk)
                                      if limits.minimum_gross_reward_risk is not None else None),
        "trade_quality_policy": (
            "warnings_only_autonomous_demo" if soft_quality_demo
            else "minimum_net_reward_risk_enforced"),
        "quality_warnings": quality_warnings,
        "effective_leverage": str(leverage),
        "slippage_assumption_each_side": str(limits.slippage_reserve_each_side),
        "approved": True,
    }
