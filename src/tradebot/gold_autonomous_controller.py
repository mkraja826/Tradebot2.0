"""Gold isolated Delta DEMO protected execution with DeepSeek decisions.

Reuses FIRE's single parent order + attached SL/TP, signed account-wide
flatness, three equity rechecks, leverage synchronization, postfill
liquidation clearance and emergency reduce-only closeout. No production host.
"""
import os
from decimal import Decimal
from pathlib import Path

from tradebot.btc_demo_size import MAX_AUTONOMOUS_LARGE_CONTRACTS
from tradebot.btc_supervised_equity_guard import SupervisedSessionEquityGuard
from tradebot.delta import DEMO_API
from tradebot.fire_account_guard import require_flat_demo_account
from tradebot.fire_execution import FireDemoController, FireTradeError
from tradebot.fire_probe import ROLES, load_snapshot
from tradebot.fire_risk import FireRiskLimits, assess_fire_plan, RiskRejected
from tradebot.gold_deepseek_probe import GOLD_MODEL, GOLD_ROLES, run_gold_deepseek_probe
from tradebot.gold_market_screen import screen_gold_market
from tradebot.gold_recent24h import load_recent24h_gold_strategy_context
from tradebot.signed_margin_mode import signed_account_margin_mode

GOLD_STRATEGY = "gold-demo-recent24h-v1"


def gold_deepseek_adapter(routes, snapshot_loader):
    """Never change the shared BTC FIRE model route."""
    if routes != ROLES:
        raise ValueError("Unexpected FIRE model route")
    return run_gold_deepseek_probe(GOLD_ROLES, snapshot_loader)


class AutoGoldController(FireDemoController):
    def __init__(self, path, *, enabled=False, **kwargs):
        if "symbol" in kwargs:
            raise ValueError("Gold autonomous controller has a fixed XAUTUSD market")
        kwargs.setdefault("probe", gold_deepseek_adapter)
        # FIRE passes the symbol explicitly to non-BTC snapshot loaders.
        kwargs.setdefault("snapshot_loader", load_snapshot)
        super().__init__(path, enabled=enabled, symbol="XAUTUSD", **kwargs)
        self.equity_guard = SupervisedSessionEquityGuard(
            self.path.parent / "fire-equity-risk.sqlite",
            allow_daily_loss_warning=True,
            allow_portfolio_loss_warnings=True,
            allow_initial_isolated_genesis=True,
            isolated_genesis_account="GOLD")
        self._gold_levels = None
        self._gold_levels_at = None
        self._gold_market_quality = False
        self._gold_account_flat = False

    def _decision_model_id(self):
        return GOLD_MODEL

    def _require_account_flat(self, exchange, product_id):
        from tradebot.gold_autonomous_demo import is_gold_armed
        if not is_gold_armed():
            raise ValueError("gold_autonomous_demo_disarmed")
        if (os.environ.get("TRADEBOT_EXPECTED_DEMO_SUBACCOUNT") != "GOLD"
                or self.path.parent.name != "gold-isolated"
                or self.path.parent.is_symlink()
                or self.path.parent.parent.is_symlink()):
            raise ValueError("gold_isolated_account_scope_required")
        if (getattr(exchange, "base_url", None) != DEMO_API
                or signed_account_margin_mode(exchange) != "isolated"):
            raise ValueError("gold_signed_isolated_margin_required")
        proof = require_flat_demo_account(
            exchange, selected_symbol=self.symbol,
            selected_product_id=product_id)
        if proof.get("account_flat_verified") is not True:
            raise ValueError("gold_broker_account_exposure_unverified")
        self._gold_account_flat = True
        return proof

    def _decision_context(self, exchange, collected, midpoint):
        if (self.path.parent.name != "gold-isolated"
                or self.path.parent.is_symlink()
                or self.path.parent.parent.is_symlink()):
            raise FireTradeError("Gold isolated data scope unavailable")
        context, levels = load_recent24h_gold_strategy_context(
            self.path.parent.parent, at=collected, price=midpoint)
        self._gold_levels = levels
        self._gold_levels_at = int(collected.timestamp()) // 300 * 300
        return context

    def _historical_levels(self, collected, midpoint):
        end = int(collected.timestamp()) // 300 * 300
        levels = self._gold_levels
        if (not isinstance(levels, dict)
                or self._gold_levels_at != end
                or levels.get("strategy_history_version") != GOLD_STRATEGY
                or levels.get("as_of") != end
                or levels.get("source") != "original_delta_demo_24h_5m_local_only"
                or set(levels.get("periods", {})) != {"last_24h"}
                or levels["periods"]["last_24h"].get("quality_status")
                    != "provisionally_valid"
                or levels.get("independent_price_validation") is not False):
            raise FireTradeError("Gold last24h historical proof unavailable")
        return levels

    def _pre_model_market_screen(self, snapshot, context):
        result = screen_gold_market(snapshot, context)
        self._gold_market_quality = result.get("status") == "passed"
        if not self._gold_market_quality:
            raise FireTradeError("Gold spread or market evidence rejected")
        return result

    def _additional_fire_scope(self):
        return {
            "strategy_history_version": GOLD_STRATEGY,
            "unattended_demo_mode": True,
            "expected_isolated_demo_subaccount": "GOLD",
            "signed_subaccount_isolated_verified": self._gold_account_flat,
            "broker_account_flat_verified": self._gold_account_flat,
            "market_data_verified": self._gold_market_quality,
            "trade_authorized": False,
            "one_attempt_operator_supervision_required": False,
            "max_new_order_attempts_per_utc_day": 48,
        }

    def _allow_wait_choice(self):
        return False

    def _hard_contract_cap(self):
        return MAX_AUTONOMOUS_LARGE_CONTRACTS

    def _max_contracts_for_entry(self, budget):
        return min(MAX_AUTONOMOUS_LARGE_CONTRACTS,
                   super()._max_contracts_for_entry(budget))

    def _model_entry_budget(self, exchange, product_id, price):
        preview = self._entry_budget(
            exchange, product_id, price, planned_leverage=20)
        return {**preview, "capacity_preview_only": True,
                "capacity_preview_leverage": 20,
                "chosen_leverage_requires_live_broker_recheck": True}

    def _normalize_plan(self, plan, context):
        """Use DeepSeek's quantity unchanged; broker/risk proofs independently gate it.

        Do not silently reduce the model's selected size to a technical
        evidence tier. The fixed demo safety cap remains independently enforced.
        """
        self._gold_sizing_record = {}
        proposed = plan.get("contracts")
        if type(proposed) is not int or not 1 <= proposed <= self._hard_contract_cap():
            return plan
        self._gold_sizing_record = {
            "policy": "gold-demo-model-selected-size-v1",
            "model_proposed_contracts": proposed,
            "selected_contracts": proposed,
            "model_selected_leverage": plan.get("leverage"),
            "quantity_auto_reduced": False,
        }
        return plan

    def _entry_sizing_record(self):
        evidence = getattr(self, "_gold_sizing_record", None)
        return {"sizing_evidence": evidence} if evidence else {}

    def _assess_risk(self, plan, budget, quote):
        size = plan.get("contracts")
        if type(size) is not int or not 1 <= size <= self._hard_contract_cap():
            raise RiskRejected("Unsupported Gold autonomous demo size")
        return assess_fire_plan(
            plan, budget, quote, limits=FireRiskLimits(
                max_contracts=self._hard_contract_cap(),
                equity_risk_fraction=None,
                minimum_net_reward_risk=None,
                minimum_gross_reward_risk=Decimal("1"),
                version="gold-demo-chart-stop-v1"))
