"""Channel-reversal profit exit for research on completed five-minute bars."""
from decimal import Decimal


def channel_profit_exit(side, fill, candles, exit_quote, cost_per_unit, lookback=10):
    """Costs are round-trip quote currency per underlying unit, including slippage.

    Candles are chronological with UTC epoch-second opening times. The caller
    supplies only completed candles and an executable bid (long) or ask (short).
    """
    if side not in ("buy", "sell") or not isinstance(lookback, int) or lookback < 2:
        raise ValueError("invalid side or channel length")
    if len(candles) < lookback + 1:
        return "insufficient_history"
    window = candles[-(lookback + 1):]
    if any(b["time"] - a["time"] != 300 for a, b in zip(window, window[1:])):
        return "incomplete_history"
    price, entry, costs = (Decimal(str(x)) for x in (exit_quote, fill, cost_per_unit))
    if not all(x.is_finite() for x in (price, entry, costs)) or min(price, entry) <= 0 or costs < 0:
        raise ValueError("invalid quote, fill or cost")
    bars = []
    for bar in window:
        low, close, high = (Decimal(str(bar[k])) for k in ("low", "close", "high"))
        if not all(x.is_finite() for x in (low, close, high)) or not 0 < low <= close <= high:
            raise ValueError("invalid candle")
        bars.append((low, close, high))
    close = bars[-1][1]
    if side == "buy":
        broken = close < min(low for low, _, _ in bars[:-1])
        gain = price - entry
    else:
        broken = close > max(high for _, _, high in bars[:-1])
        gain = entry - price
    return "take_profit" if broken and gain > costs else "hold"
