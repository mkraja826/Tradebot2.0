"""BTC demo strategy arithmetic. Prices and wallet values use settlement units."""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

D = Decimal


def entry_plan(direction, wallet, bid, ask, contract_value, tick, atr):
    """Use the scanner direction and ATR14 of completed five-minute bars."""
    if direction == "NEUTRAL":
        return None
    if direction not in ("LONG", "SHORT"):
        raise ValueError("unknown scanner direction")
    wallet, bid, ask, contract_value, tick, atr = map(
        lambda x: D(str(x)), (wallet, bid, ask, contract_value, tick, atr))
    if min(wallet, bid, ask, contract_value, tick, atr) <= 0 or bid > ask:
        raise ValueError("invalid market or account data")
    long = direction == "LONG"
    entry = ask if long else bid
    size = int(wallet * D("0.20") * 20 / (entry * contract_value))
    if size == 0:
        return None
    raw_stop = entry + (-1 if long else 1) * D("1.5") * atr
    rounding = ROUND_FLOOR if long else ROUND_CEILING
    stop = (raw_stop / tick).to_integral_value(rounding=rounding) * tick
    if stop <= 0:
        raise ValueError("invalid stop")
    return dict(side="buy" if long else "sell", size=size, leverage=20,
                entry_reference=entry, stop_loss=stop)


def trailing_stop(side, fill, initial_stop, current_stop, close, ema9, atr, tick):
    """Update after a completed five-minute bar. Caller persists accepted stops."""
    fill, initial_stop, current_stop, close, ema9, atr, tick = (
        D(str(x)) for x in (fill, initial_stop, current_stop, close, ema9, atr, tick))
    if side not in ("buy", "sell") or min(fill, initial_stop, current_stop, close, ema9, atr, tick) <= 0:
        raise ValueError("invalid trailing inputs")
    sign = 1 if side == "buy" else -1
    risk = sign * (fill - initial_stop)
    if risk <= 0:
        raise ValueError("invalid original risk")
    if sign * (close - fill) < risk:
        return current_stop
    raw = ema9 - sign * D("0.25") * atr
    rounding = ROUND_FLOOR if sign == 1 else ROUND_CEILING
    candidate = (raw / tick).to_integral_value(rounding=rounding) * tick
    if candidate <= 0 or sign * (close - candidate) <= 0:
        return current_stop
    return max(current_stop, candidate) if sign == 1 else min(current_stop, candidate)
