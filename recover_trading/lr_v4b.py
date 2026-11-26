"""Recover LR-V4-B deterministic strategy primitives; no broker side effects.

Candidate research integration only. Candle timestamps are UTC opening seconds.
Liquidation events are bucketed by receipt time, not exchange event time.
All candles supplied to these functions must be final and contiguous.
"""
from math import ceil, isfinite

VERSION = "lr-v4b"
HOLD_MINUTES = 60
TARGET_R = 2.0
ACTIVATE_R = 0.5
COST_BPS = 15.0


def _candles(rows):
    rows = list(rows)
    previous = None
    for row in rows:
        t = row["time"]
        o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        if (type(t) is not int or t % 60 or
                (previous is not None and t != previous + 60) or
                not all(isfinite(x) and x > 0 for x in (o, h, l, c)) or
                not l <= min(o, c) <= max(o, c) <= h):
            raise ValueError("invalid or noncontiguous closed candles")
        previous = t
    return rows


def _ema(rows):
    values = []
    for row in rows:
        close = float(row["close"])
        values.append(close if not values else 0.2 * close + 0.8 * values[-1])
    return values


def _atr(rows, i):
    return sum(max(float(rows[k]["high"]) - float(rows[k]["low"]),
                   abs(float(rows[k]["high"]) - float(rows[k-1]["close"])),
                   abs(float(rows[k]["low"]) - float(rows[k-1]["close"])))
               for k in range(i-13, i+1)) / 14


def signals(candles, events, *, covered_through):
    """Emit confirmed reclaim decisions at candle close; never assumes a fill.

    covered_through is the conservative exclusive UTC coverage cutoff in seconds.
    An upstream adapter must verify collector continuity and supply only closed
    candles and immutable event snapshots. Empty bins alone are not that proof.
    """
    rows = _candles(candles)
    if not rows:
        return []
    if rows[-1]["time"] + 60 > covered_through:
        raise ValueError("candle exceeds conservative archive cutoff")
    ema = _ema(rows)
    bins = [[0.0, 0.0] for _ in rows]
    seen = set()
    start = rows[0]["time"]
    for event in events:
        key = (event["batch_id"], event["ordinal"])
        if key in seen:
            continue
        seen.add(key)
        t = event["received_ms"]
        size = float(event["size_btc"])
        side = event["liquidated_position_side"]
        if type(t) is not int or not isfinite(size) or size <= 0 or side not in ("LONG", "SHORT"):
            raise ValueError("invalid liquidation event")
        i = (t // 60000 * 60 - start) // 60
        if 0 <= i < len(rows):
            bins[i][0 if side == "LONG" else 1] += size

    def total(i):
        return [sum(bins[k][s] for k in range(i-2, i+1)) for s in (0, 1)]

    out = []
    last = -100
    for i in range(122, len(rows)):
        a, b = total(i)
        v = a + b
        if v < 0.5 or max(a, b) / v < 0.7 or i-last <= 3:
            continue
        hist = sorted(sum(total(j)) for j in range(i-120, i-2))
        if v < hist[ceil(len(hist)*0.95)-1]:
            continue
        last = i
        d = 1 if a >= b else -1
        extreme_key = "low" if d == 1 else "high"
        extreme_fn = min if d == 1 else max
        level = extreme_fn(float(r[extreme_key]) for r in rows[i-22:i-2])
        sweep = extreme_fn(float(r[extreme_key]) for r in rows[i-2:i+1])
        atr = _atr(rows, i-3)
        if atr <= 0 or d*(level-sweep) < 0.1*atr:
            continue
        for j in range(i, min(i+6, len(rows))):
            r = rows[j]
            close = float(r["close"])
            if d*(close-level) <= 0:
                continue
            # First reclaim is decisive; do not search later candles after failure.
            if (d*(close-float(r["open"])) > 0 and
                    d*(close-ema[j]) > 0 and d*(ema[j]-ema[j-1]) > 0 and
                    d*(close-level) <= atr):
                extreme = extreme_fn(float(x[extreme_key]) for x in rows[i-2:j+1])
                out.append({"version": VERSION, "symbol": "BTCUSD",
                            "side": "buy" if d == 1 else "sell",
                            "burst_time": rows[i]["time"]+60,
                            "signal_time": r["time"]+60,
                            "initial_stop": extreme-d*0.1*atr,
                            "liquidation_btc": v, "atr": atr})
            break
    return out


def bracket(side, fill, stop):
    """Compute the original R and 2R target using the actual entry fill."""
    if side not in ("buy", "sell"):
        raise ValueError("unsupported side")
    d = 1 if side == "buy" else -1
    fill, stop = float(fill), float(stop)
    risk = d*(fill-stop)
    target = fill+d*TARGET_R*risk
    if not all(isfinite(x) and x > 0 for x in (fill, stop, risk, target)):
        raise ValueError("invalid structural bracket")
    return {"entry": fill, "initial_stop": stop, "risk": risk, "target": target}


def trail(side, entry, initial_stop, current_stop, closed_candle, ema9, activated=False):
    """One closed post-entry candle. Stop becomes effective next cycle.

    Caller must persist activation, reconcile broker state and enforce attribution.
    This returns a proposal only, not a broker amendment.
    """
    b = bracket(side, entry, initial_stop)
    d = 1 if side == "buy" else -1
    close = float(closed_candle["close"])
    high, low = float(closed_candle["high"]), float(closed_candle["low"])
    ema9, current_stop = float(ema9), float(current_stop)
    if (not all(isfinite(x) and x > 0 for x in (close, high, low, ema9, current_stop))
            or not low <= close <= high or d*(current_stop-b["initial_stop"]) < 0):
        raise ValueError("invalid trailing state")
    favourable = high if d == 1 else low
    active = bool(activated or d*(favourable-b["entry"])/b["risk"] >= ACTIVATE_R)
    candidate = min(ema9, close) if d == 1 else max(ema9, close)
    proposed = (max(current_stop, candidate) if d == 1 else min(current_stop, candidate)) if active else current_stop
    return {"activated": active, "proposed_stop": proposed, "target": b["target"],
            "execution_effect": "none"}
