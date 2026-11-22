"""Isolated supervised BTC-only controller using existing FIRE protection.

No dashboard setting chooses this controller. Only the separate explicitly
approved one-attempt operator command may instantiate it with enabled=True.
The original normal FIRE controller, durable entries, cross-market portfolio
reservation, signed account-wide exposure, liquidation safeguards and
independent watchdog remain in force.
"""
from tradebot.btc_supervised_equity_guard import SupervisedSessionEquityGuard
from tradebot.btc_supervised_recent24h import load_recent24h_strategy_context
from tradebot.btc_market_screen import screen_btc_market
from tradebot.btc_public_reference import (read_coinbase_spot, corroborate_delta_quote)
from tradebot.fire_execution import FireDemoController, FireTradeError

STRATEGY_VERSION = "btc-demo-recent24h-v1"


class SupervisedBTCController(FireDemoController):
    def __init__(self, path, *, enabled=False, **kwargs):
        if "symbol" in kwargs:
            raise ValueError("BTC supervised controller has fixed BTCUSD symbol")
        super().__init__(path, enabled=enabled, symbol="BTCUSD", **kwargs)
        self.equity_guard = SupervisedSessionEquityGuard(
            self.path.parent / "fire-equity-risk.sqlite"
        )
        self._restricted_levels = None
        self._restricted_at = None

    def _decision_context(self, exchange, collected, midpoint):
        # Fail before any model call when recent source is unavailable.
        context, levels = load_recent24h_strategy_context(
            self.path.parent, at=collected, price=midpoint
        )
        self._restricted_levels = levels
        self._restricted_at = int(collected.timestamp()) // 300 * 300
        return context

    def _historical_levels(self, collected, midpoint):
        # Do not produce fake current/previous month quality flags. The
        # separately scoped model must see one actual 24h range only.
        boundary = int(collected.timestamp()) // 300 * 300
        levels = self._restricted_levels
        if (not isinstance(levels, dict)
                or self._restricted_at != boundary
                or levels.get("strategy_history_version") != STRATEGY_VERSION
                or levels.get("as_of") != boundary
                or levels.get("source") != "original_delta_demo_24h_5m_local_only"
                or set(levels.get("periods", {})) != {"last_24h"}
                or levels["periods"]["last_24h"].get("quality_status")
                    != "provisionally_valid"
                or levels.get("independent_price_validation") is not False):
            raise FireTradeError("Unverified supervised BTC 24h history")
        return levels

    def _pre_model_market_screen(self, snapshot, context):
        # Deterministic no-AI rejection before the GPT-6 request.
        local = screen_btc_market(snapshot, context)
        # A keyless public GET can reject dislocated Delta prices before GPT.
        # This is independent spot context, not a Delta perp print attestation.
        reference = corroborate_delta_quote(snapshot, read_coinbase_spot())
        return {**local, "external_spot_reference": reference}

    def _additional_fire_scope(self):
        return {"strategy_history_version": STRATEGY_VERSION,
                "one_attempt_operator_supervision_required": True}
