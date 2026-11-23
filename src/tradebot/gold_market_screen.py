"""Deterministic, no-AI Gold demo market-cost screen before GPT-6.

Only for separately supervised Gold entry decisions. It adds a conservative
filter; never grants broker execution permission or validates candle origin.
"""
from decimal import Decimal, InvalidOperation

MAX_SPREAD_BPS = Decimal("10")
MAX_MARK_DEVIATION_BPS = Decimal("50")
MAX_ATR_BPS = Decimal("500")
MAX_SPREAD_TO_ATR = Decimal("0.25")
BPS = Decimal("10000")


class MarketScreenRejected(ValueError):
    """Fixed reason codes only; no untrusted quote text."""


def _positive(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0 or isinstance(value, bool):
            raise ValueError
        return result
    except (InvalidOperation, TypeError, ValueError):
        raise MarketScreenRejected("market_screen_invalid_number") from None


def screen_gold_market(snapshot, context):
    """Reject costly/stale-quality setups before a paid GPT-6 completion."""
    if not isinstance(snapshot, dict) or not isinstance(context, dict):
        raise MarketScreenRejected("market_screen_invalid_context")
    core = snapshot.get("core")
    if not isinstance(core, dict) or not isinstance(core.get("ticker"), dict):
        raise MarketScreenRejected("market_screen_invalid_context")
    if core["ticker"].get("symbol") != "XAUTUSD":
        raise MarketScreenRejected("market_screen_wrong_market")
    bid = _positive(core.get("best_bid"))
    ask = _positive(core.get("best_ask"))
    mark = _positive(core["ticker"].get("mark_price"))
    atr = _positive(context.get("atr_5m"))
    if ask < bid:
        raise MarketScreenRejected("market_screen_crossed_quote")
    midpoint = (bid + ask) / 2
    spread_bps = (ask - bid) / midpoint * BPS
    mark_bps = abs(mark - midpoint) / midpoint * BPS
    atr_bps = atr / midpoint * BPS
    if spread_bps > MAX_SPREAD_BPS:
        raise MarketScreenRejected("market_screen_spread_too_wide")
    if mark_bps > MAX_MARK_DEVIATION_BPS:
        raise MarketScreenRejected("market_screen_mark_dislocation")
    if atr_bps > MAX_ATR_BPS:
        raise MarketScreenRejected("market_screen_extreme_volatility")
    if (ask - bid) > atr * MAX_SPREAD_TO_ATR:
        raise MarketScreenRejected("market_screen_spread_vs_volatility")
    for period in ("ema_15m", "ema_1h"):
        trend = context.get(period)
        if not isinstance(trend, dict):
            raise MarketScreenRejected("market_screen_trend_unavailable")
        _positive(trend.get("ema20"))
        _positive(trend.get("close"))
        if trend.get("slope") not in ("rising", "falling", "flat"):
            raise MarketScreenRejected("market_screen_trend_unavailable")
    vwap = context.get("session_vwap")
    if vwap is not None:
        _positive(vwap)
    return {
        "status": "passed",
        "spread_bps": str(spread_bps.quantize(Decimal("0.001"))),
        "mark_deviation_bps": str(mark_bps.quantize(Decimal("0.001"))),
        "atr_bps": str(atr_bps.quantize(Decimal("0.001"))),
        "source": "local_market_snapshot_only",
        "independent_price_verified": False,
        "trade_authorized": False,
    }
