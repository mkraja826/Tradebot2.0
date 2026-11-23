"""Evidence-based sizing ceiling for BTCUSD Delta India DEMO only.

A weaker but still acceptable GPT-6 entry remains one contract. Medium and
strong corroborated directional setups may request two and three contracts;
this module
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


def _setup_score(context, direction):
    """Return (ADX, aligned-independent-confirmations), or None when unverified.

    Signal counts are deterministic *capacity limits* only; they never
    authorize entry, override GPT's WAIT or bypass broker-side safeguards.
    """
    if direction not in ("LONG", "SHORT") or not isinstance(context, dict):
        return None
    up = direction == "LONG"

    def favors(a, b):
        return a > b if up else a < b

    try:
        near = context["ema_15m"]
        far = context["ema_1h"]
        if not isinstance(near, dict) or not isinstance(far, dict):
            return None
        for row in (near, far):
            if row.get("slope") != ("rising" if up else "falling"):
                return None
            close, ema = _number(row.get("close")), _number(row.get("ema20"))
            if close is None or ema is None or not favors(close, ema):
                return None

        indicators = context["technical_5m"]
        adx = indicators["adx14"]
        if not isinstance(indicators, dict) or not isinstance(adx, dict):
            return None
        adx_value = _number(adx.get("adx14"))
        plus = _number(adx.get("plus_di14"))
        minus = _number(adx.get("minus_di14"))
        if (adx_value is None or adx_value < Decimal("20")
                or plus is None or minus is None
                or not favors(plus, minus)):
            return None

        confirms = 0
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
        return adx_value, confirms
    except (KeyError, AttributeError, TypeError, ValueError):
        return None


def strong_directional_setup(context, direction):
    """Only strong, corroborated entries qualify for the largest size."""
    score = _setup_score(context, direction)
    return score is not None and score[0] >= 25 and score[1] >= 3


def evidence_contract_ceiling(context, direction):
    """Small=1, medium=2, strong=3; WAIT=0, never an entry authorization."""
    if direction == "WAIT":
        return 0
    score = _setup_score(context, direction)
    if score is None:
        return 1
    adx, confirmations = score
    if adx >= 25 and confirmations >= 3:
        return 3
    if confirmations >= 1:
        return 2
    return 1
