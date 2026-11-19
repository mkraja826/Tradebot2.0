"""Point-in-time market context for a manual FIRE decision."""
from math import isfinite

from tradebot.chart_desk import epoch


def _trend(bars, end, minutes):
    step = minutes * 60
    boundary = end // step * step
    closes = []
    for finish in range(boundary, min(bars, default=boundary), -step):
        if any(t not in bars for t in range(finish-step, finish, 300)):
            break
        closes.append(bars[finish-300][2])
    closes.reverse()
    if len(closes) < 21:
        return None
    ema = sum(closes[:20]) / 20
    for close in closes[20:]:
        previous = ema
        ema += (close - ema) * 2 / 21
    return {"ema20": round(ema, 6), "slope": "rising" if ema > previous else
            "falling" if ema < previous else "flat", "close": closes[-1]}


def indicators(rows, end, price, exit_fill=None):
    boundary = int(end) // 300 * 300
    bars = {}
    for row in rows:
        try:
            t = int(row["time"])
            high, low, close, volume = (float(row[k]) for k in ("high", "low", "close", "volume"))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if t >= boundary or t % 300:
            continue
        if (not all(map(isfinite, (high, low, close, volume))) or
                not 0 < low <= close <= high or volume < 0):
            continue
        bars[t] = high, low, close, volume
    context = {"as_of": boundary, "ema_15m": _trend(bars, boundary, 15),
               "ema_1h": _trend(bars, boundary, 60), "atr_5m": None,
               "session_vwap": None, "since_exit": None}
    midnight = boundary // 86400 * 86400
    session = [bars.get(t) for t in range(midnight, boundary, 300)]
    if session and all(session):
        volume = sum(b[3] for b in session)
        if volume:
            context["session_vwap"] = round(sum(sum(b[:3])/3*b[3] for b in session)/volume, 6)
    # Wilder ATR seeded with the mean of the first 14 consecutive true ranges.
    atr = None
    ranges = []
    for t in range(boundary-300, min(bars, default=boundary), -300):
        if t not in bars or t-300 not in bars:
            break
        high, low = bars[t][:2]
        prev = bars[t-300][2]
        ranges.append(max(high-low, abs(high-prev), abs(low-prev)))
    if len(ranges) >= 14:
        ranges.reverse()
        atr = sum(ranges[:14])/14
        for tr in ranges[14:]:
            atr += (tr-atr)/14
        context["atr_5m"] = round(atr, 6)
    if exit_fill and exit_fill["at"] <= end:
        move = price - exit_fill["price"]
        last_full = int(exit_fill["at"] // 300) * 300 - 300
        first_after = int(-(-exit_fill["at"] // 300)) * 300
        after = [bars.get(t) for t in range(first_after, boundary, 300)] if last_full in bars else []
        reference = bars.get(last_full)
        comparable = bool(after and all(after))
        context["since_exit"] = {"broke_pre_exit_high": any(b[0] > reference[0] for b in after) if comparable else None,
                                 "broke_pre_exit_low": any(b[1] < reference[1] for b in after) if comparable else None,
                                 **exit_fill, "seconds": int(end-exit_fill["at"]),
                                 "move": round(move, 6),
                                 "move_atr": round(move/atr, 3) if atr else None}
    return context


def previous_exit(exchange, previous, symbol, end):
    if not previous:
        return None
    fills = []
    for kind, oid in (previous.get("exit_order_ids") or {}).items():
        if not str(oid).isdigit():
            continue
        row = exchange._request("GET", "/v2/orders/" + str(oid), auth=True)["result"]
        if (str(row.get("id")) != str(oid) or (row.get("product_symbol") or row.get("symbol")) != symbol
                or row.get("state") != "closed" or float(row["unfilled_size"]) != 0
                or row.get("side") != ("sell" if previous.get("direction") == "LONG" else "buy")
                or float(row["size"]) != previous.get("contracts")):
            continue
        price, at = float(row["average_fill_price"]), epoch(row.get("updated_at"))
        if at and at <= end and isfinite(price) and price > 0:
            fills.append({"price": price, "at": at, "kind": kind})
    return fills[0] if len(fills) == 1 else None


def decision_context(exchange, store, symbol, end, price):
    try:
        rows = exchange.candles(symbol=symbol, resolution="5m", start=int(end)-48*3600, end=int(end))
    except (AttributeError, OSError, RuntimeError, ValueError):
        rows = []
    try:
        last = previous_exit(exchange, store.last_closed_position(), symbol, end)
    except (KeyError, TypeError, ValueError, OSError, RuntimeError):
        last = None
    return indicators(rows, end, price, last)
