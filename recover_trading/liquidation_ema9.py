"""BTC liquidation-entry / EMA9 exit research. No broker or execution imports.

Consumes the existing timestamped Bybit BTCUSDT hypothesis journal and Delta
BTCUSD candles. Research only: no live orders, no AI calls, no database writes.
"""
import argparse
import json
import math
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from .tb2_backtest_tools import (
    VARIANTS, COSTS, check_window, indicators, load_bars, metrics, simulate,
)

VERSION = "liquidation-ema9-research-v1"
# Frozen illustrative research hypotheses, not fitted parameters.
BURST_MS = 300_000
CONFIRM_MINUTES = 5
HOLD_MINUTES = 60
ENTRY_SLIPPAGE_BPS = 2
FEE_BPS = 15
EMA_STEP = 900
SOURCE = "bybit_public_linear_BTCUSDT"


def burst_side(observed_ms, payload):
    """Require archived actual liquidation observations, not a wick proxy."""
    if (type(observed_ms) is not int or payload.get("source") != SOURCE
            or payload.get("status") != "observed_research_only"):
        return None
    stamp = payload.get("as_of_ms")
    if type(stamp) is not int or not 0 <= observed_ms - stamp <= 120_000:
        return None
    try:
        f = payload["features"]
        move = float(f["price_move_bps"])
        oi = float(f["oi_change_pct"])
        if not math.isfinite(move) or not math.isfinite(oi) or oi > -.1:
            return None
        side = "LONG" if move <= -20 else "SHORT" if move >= 20 else None
        if side is None:
            return None
        size = float(f["observed_sizes_btc"][side])
        count = f["observed_counts"][side]
        if not math.isfinite(size) or size < 1 or type(count) is not int or count < 2:
            return None
        return side
    except (KeyError, ValueError, TypeError, OverflowError):
        return None


def confirm(side, observed_ms, minute):
    """First completed post-observation candle closing outside the prior range.
    Entry is no earlier than the following minute open. No wick-only fills.
    """
    floor = observed_ms // 60_000 * 60
    first = (observed_ms + 59_999) // 60_000 * 60
    reference = minute.get(floor - 60)
    if reference is None:
        return None
    _, high, low, _, *_ = reference
    for t in range(first, first + CONFIRM_MINUTES * 60, 60):
        row = minute.get(t)
        if row is None:
            return None
        close = row[3]
        if close > high or close < low:
            sign = 1 if close > high else -1
            cascade_sign = -1 if side == "LONG" else 1
            return t + 60, sign, "continuation" if sign == cascade_sign else "reversal"
    return None


def prepare_entry(entry_at, sign, minute, ema1, ema15, end):
    """Synthetic bracket: structural stop + 0.25 ATR, fixed 2R target.
    This is a reproducible research proxy, NOT an AI-selected bracket.
    """
    last = entry_at + HOLD_MINUTES * 60
    if last > end:
        return None, "incomplete_horizon"
    if any(t not in minute for t in range(entry_at - 300, last, 60)):
        return None, "missing_minute_path"
    if entry_at not in ema1 or any(t // EMA_STEP * EMA_STEP not in ema15
                                   for t in range(entry_at, last, 60)):
        return None, "missing_indicator_warmup"
    entry = minute[entry_at][0] * (1 + sign * ENTRY_SLIPPAGE_BPS / 10000)
    atr = ema1[entry_at][2]
    bars = [minute[t] for t in range(entry_at - 300, entry_at, 60)]
    sl = min(b[2] for b in bars) - .25 * atr if sign == 1 else max(b[1] for b in bars) + .25 * atr
    risk = sign * (entry - sl)
    tp = entry + sign * 2 * risk
    if not all(math.isfinite(v) and v > 0 for v in (entry, sl, tp, risk, atr)):
        return None, "invalid_bracket"
    return dict(id=str(entry_at), opened=entry_at, closed=last, first=entry_at,
                last=last, sign=sign, entry=entry, qty=1 / entry,
                rate=FEE_BPS / 20000, sl=sl, tp=tp, target_at_entry=tp,
                actual=None), None


def analyze(observations, minute, ema1, ema15, start, split, end):
    """Chronological, non-overlapping matched exit trials. No strategy selection."""
    if not start < split < end:
        raise ValueError("split must be inside window")
    excluded = Counter()
    trades = []
    next_burst_ms = 0
    reserved_until = 0
    for stamp, payload in sorted(observations, key=lambda x: x[0]):
        if not start * 1000 <= stamp < end * 1000:
            continue
        side = burst_side(stamp, payload)
        if side is None:
            excluded["not_qualifying_observation"] += 1
            continue
        if stamp < next_burst_ms:
            excluded["burst_overlap"] += 1
            continue
        # Reserve before seeing confirmation or outcomes.
        next_burst_ms = stamp + BURST_MS
        if stamp < reserved_until * 1000:
            excluded["reserved_position_window"] += 1
            continue
        match = confirm(side, stamp, minute)
        if match is None:
            excluded["no_confirmed_entry_or_missing_candle"] += 1
            continue
        entry_at, sign, kind = match
        partition = "development" if stamp < split * 1000 else "holdout"
        horizon_end = split if partition == "development" else end
        if entry_at >= horizon_end:
            excluded["split_boundary"] += 1
            continue
        reserved_until = entry_at + HOLD_MINUTES * 60
        t, reason = prepare_entry(entry_at, sign, minute, ema1, ema15, horizon_end)
        if t is None:
            excluded[reason] += 1
            continue
        fixed = simulate(t, minute, ema15, EMA_STEP, VARIANTS["baseline"], "original")
        adaptive = simulate(t, minute, ema15, EMA_STEP, VARIANTS["V8"], "original")
        trades.append(dict(observed_ms=stamp, entry_at=entry_at, direction="LONG" if sign == 1 else "SHORT",
                           liquidation_side=side, kind=kind, partition=partition,
                           initial_stop=t["sl"], target=t["tp"], entry_price=t["entry"],
                           fixed=fixed, adaptive=adaptive))
    summaries = []
    for partition in ("development", "holdout"):
        for kind in ("reversal", "continuation", "all"):
            rows = [r for r in trades if r["partition"] == partition and (kind == "all" or r["kind"] == kind)]
            for cost in map(str, COSTS):
                fixed = [r["fixed"]["net"][cost] * 10000 for r in rows]
                adaptive = [r["adaptive"]["net"][cost] * 10000 for r in rows]
                diff = [b - a for a, b in zip(fixed, adaptive)]
                summaries.append(dict(partition=partition, kind=kind, exit_slippage_bps=int(cost),
                                      n=len(rows), fixed_bps=metrics(fixed), adaptive_bps=metrics(adaptive),
                                      improvement_bps=round(sum(diff), 6),
                                      improved=sum(d > 1e-8 for d in diff), worse=sum(d < -1e-8 for d in diff)))
    return dict(version=VERSION, execution_effect="none", status="observed" if trades else "no_eligible_entries",
                symbol="BTCUSD", start=start, split=split, end=end, trades=trades,
                exclusions=dict(excluded), summaries=summaries,
                assumptions=dict(round_trip_fee_bps=FEE_BPS, entry_slippage_bps=ENTRY_SLIPPAGE_BPS,
                                 hold_minutes=HOLD_MINUTES, stop="five completed minutes +/- 0.25 ATR",
                                 target="fixed 2R proxy, not AI", ema_variant="15m V8"),
                limitations=[
                    "Reference Bybit BTCUSDT events; not Delta liquidation events. Event completeness unverified.",
                    "Archived observations are not proof of continuous market coverage.",
                    "Trade-price OHLC proxy, not executable quotes or mark triggers; stop-first on dual touch.",
                    "Equal unit notional; no leverage, funding, liquidation, AI costs or portfolio simulation.",
                    "Selection and thresholds are experimental; holdout is chronological, not guaranteed unseen.",
                    "Gold unavailable without a verified XAUT liquidation source.",
                    "Matched liquidation-entry exit comparison only; existing strategy benchmark is separate.",
                ])


def run(root, journal, start, split, end):
    check_window(start, end)
    if not start < split < end:
        raise ValueError("split must be inside window")
    with closing(sqlite3.connect(Path(journal).resolve().as_uri() + "?mode=ro",
                                 uri=True, timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        rows = [(s, json.loads(p)) for s, p in db.execute(
            "SELECT observed_ms,payload FROM observations WHERE observed_ms>=? AND observed_ms<? ORDER BY observed_ms",
            (start * 1000, end * 1000))]
    root = Path(root)
    minute, bad1 = load_bars(root, "BTCUSD", "1m", max(0, start // 60 * 60 - 106 * 60), end)
    slow, bad15 = load_bars(root, "BTCUSD", "15m", max(0, start // EMA_STEP * EMA_STEP - 106 * EMA_STEP), end)
    out = analyze(rows, minute, indicators(minute, 60), indicators(slow, EMA_STEP), start, split, end)
    out.update(observation_count=len(rows), invalid_candles={"1m": bad1, "15m": bad15})
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--market-root", required=True)
    p.add_argument("--hypotheses-db", required=True)
    for name in ("start", "split", "end"):
        p.add_argument("--" + name, required=True, type=int)
    a = p.parse_args()
    try:
        out = run(a.market_root, a.hypotheses_db, a.start, a.split, a.end)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        out = dict(version=VERSION, execution_effect="none", status="research_data_unavailable_or_invalid",
                   error_type=type(exc).__name__)
    print(json.dumps(out, allow_nan=False))


if __name__ == "__main__":
    main()
