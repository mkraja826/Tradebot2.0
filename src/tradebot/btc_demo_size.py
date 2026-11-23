"""Evidence-based sizing ceiling for BTCUSD Delta India DEMO only.

A weaker but still acceptable GPT-6 entry remains one contract. Only a
strong, corroborated directional setup may request two contracts; this module
cannot turn WAIT into a trade or authorize broker execution. Independent risk,
equity, margin, liquidation and bracket gates still control actual execution.
"""
from decimal import Decimal, InvalidOperation


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        x = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return x if x.is_finite() else None


def strong_directional_setup(context, direction):
    """Require aligned EMA trend, ADX/DI and multiple independent confirmations."""
    if direction not in ("LONG", "SHORT") or not isinstance(context, dict):
        return False
    up = direction == "LONG"

    def favors(a, b):
        return a > b if up else a < b

    try:
        near = context["ema_15m"]
        far = context["ema_1h"]
        if not isinstance(near, dict) or not isinstance(far, dict):
            return False
        for row in (near, far):
            if row.get("slope") != ("rising" if up else "falling"):
                return False
            if not favors(_number(row["close"]), _number(row["ema20"])):
                return False

        indicators = context["technical_5m"]
        adx = indicators["adx14"]
        if not isinstance(indicators, dict) or not isinstance(adx, dict):
            return False
        adx_value = _number(adx["adx14"])
        plus = _number(adx["plus_di14"])
        minus = _number(adx["minus_di14"])
        if not (adx_value is not None and adx_value >= 25
                and plus is not None and minus is not None
                and favors(plus, minus)):
            return False

        confirms = 2  # EMA and ADX/DI are required, not interchangeable.
        macd = indicators.get("macd_12_26_9")
        if isinstance(macd, dict):
            h = _number(macd.get("histogram"))
            confirms += int(h is not None and (h > 0 if up else h < 0))
        rsi = _number(indicators.get("rsi14"))
        confirms += int(rsi is not None and (
            Decimal("55") <= rsi <= Decimal("70") if up
            else Decimal("30") <= rsi <= Decimal("45")))
        vwap = _number(context.get("session_vwap"))
        close = _number(near.get("close"))
        confirms += int(vwap is not None and close is not None and favors(close, vwap))
        rvol = indicators.get("relative_volume20")
        if isinstance(rvol, dict) and rvol.get("status") == "available":
            x = _number(rvol.get("ratio"))
            confirms += int(x is not None and x >= Decimal("1.10"))
        return confirms >= 4
    except (KeyError, AttributeError, TypeError, ValueError):
        return False


def evidence_contract_ceiling(context, direction):
    """Advisory demo-only contract ceiling. No broker authority is granted."""
    if direction == "WAIT":
        return 0
    return 2 if strong_directional_setup(context, direction) else 1
