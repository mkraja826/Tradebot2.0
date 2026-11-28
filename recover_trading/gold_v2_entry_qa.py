"""Read-only explanation of Gold mark entry signals using the worker's own scan."""
import json
import operator
import sqlite3
from contextlib import closing

from .gold_v2_engine import ema
from .gold_v2_technical import momentum

OPS = {"==": operator.eq, ">": operator.gt, ">=": operator.ge,
       "<": operator.lt, "<=": operator.le}


def check(value, op, target):
    known = value is not None and target is not None
    return {"value": value, "operator": op, "threshold": target,
            "passed": OPS[op](value, target) if known else None}


def explain(primary, report):
    audit = {"model": report["version"], "data_status": report["status"],
             "data_quality": report["data_quality"], "setups": {},
             "engine_candidates": [(c["family"], c["direction"]) for c in report["candidates"]],
             "matches_engine": None}
    if report["status"] != "observed":
        return audit
    bars = primary[300]
    prior, last = bars[-2:]
    features = report["features"]
    fast = features[300]
    atr = fast["atr"]
    ema9, ema21 = fast["ema"][:2]
    prev9 = ema([b.c for b in bars[:-1]], 9)
    prev_rsi = momentum(bars[:-1])
    audit["bar_closed_at"] = last.ts
    audit["five_minute_candles"] = [
        [b.ts, b.o, b.h, b.l, b.c] for b in bars[-22:]]
    audit["features"] = features
    predicted = set()
    for side, direction in ((1, "LONG"), (-1, "SHORT")):
        aligned = {"hour_direction": check(features[3600]["direction"], "==", side),
                   "quarter_hour_direction": check(features[900]["direction"], "==", side)}
        trend = dict(aligned, ema21_50_gap_atr=check(features[900]["separation_atr"], ">=", .5))
        def level(window, high):
            return max(b.h for b in window) if high else min(b.l for b in window)
        long = side == 1
        breakout = level(bars[-21:-1], long)
        retest = level(bars[-22:-2], long)
        rejection = level(bars[-22:-2], not long)
        extreme = last.l if long else last.h
        swing = fast.get("last_swing_high" if long else "last_swing_low")
        threshold = 30 if long else 70
        setups = {
            "mark_trend_pullback": dict(trend,
                prior_close_vs_ema9=check(side*(prior.c-prev9), "<=", 0),
                close_vs_ema9=check(side*(last.c-ema9), ">", 0),
                ema9_vs_ema21=check(side*(ema9-ema21), ">", 0)),
            "mark_structure_breakout": dict(trend,
                close_beyond_range=check(side*(last.c-breakout), ">", .15*atr),
                adx=check(fast.get("adx"), ">=", 25)),
            "mark_breakout_retest": dict(aligned,
                prior_break=check(side*(prior.c-retest), ">", .15*atr),
                retest_distance=check(abs(extreme-retest), "<=", .25*atr),
                closing_distance=check(side*(last.c-retest), ">", .1*atr)),
            "mark_range_rejection": {
                "penetration": check(side*(extreme-rejection), "<", -.1*atr),
                "recovery": check(side*(last.c-rejection), ">", .1*atr),
                "candle_body": check(side*(last.c-last.o), ">", .1*atr)},
            "mark_rsi_reversal": {
                "adx": check(fast.get("adx"), "<", 20),
                "previous_rsi": check(prev_rsi, "<=" if long else ">=", threshold),
                "current_rsi": check(fast.get("rsi14"), ">" if long else "<", threshold)},
            "mark_swing_continuation": dict(aligned,
                adx=check(fast.get("adx"), ">=", 25),
                directional_index=check(fast.get("plus_di" if long else "minus_di"), ">",
                                        fast.get("minus_di" if long else "plus_di")),
                structure=check(fast.get("structure"), "==",
                                "higher_highs_lows" if long else "lower_highs_lows"),
                prior_swing_distance=check(None if swing is None else side*(prior.c-swing), "<=", 0),
                close_swing_distance=check(None if swing is None else side*(last.c-swing), ">", .1*atr))}
        audit["setups"][direction] = setups
        for family, conditions in setups.items():
            if all(c["passed"] is True for c in conditions.values()):
                predicted.add((family, direction))
    audit["matches_engine"] = predicted == set(audit["engine_candidates"])
    return audit


def record(root, boundary, started, event, snapshot):
    details = explain(*snapshot) if snapshot else None
    payload = {"scan": details, "controller": event.get("controller"), "errors": event["errors"],
               "runtime": event["version"], "symbol": event["symbol"]}
    with closing(sqlite3.connect(root / "entry_qa.sqlite", timeout=0.1)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS scans (
            boundary INTEGER NOT NULL, started INTEGER NOT NULL,
            finished INTEGER NOT NULL, detail TEXT NOT NULL,
            PRIMARY KEY(boundary, started))""")
        db.execute("INSERT OR IGNORE INTO scans VALUES(?,?,?,?)",
                   (boundary, started, event["timestamp"], json.dumps(payload, allow_nan=False)))


def summary(path, since):
    """Use the latest attempt per boundary so retries do not inflate counts."""
    from collections import Counter
    totals = Counter()
    failures = Counter()
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute("""SELECT detail FROM scans JOIN
            (SELECT boundary, max(started) AS started FROM scans WHERE boundary >= ?
             GROUP BY boundary) USING (boundary, started) ORDER BY boundary""", (since,))
        for (detail,) in rows:
            event = json.loads(detail)
            totals["entry_boundaries_recorded"] += 1
            scan = event["scan"]
            if scan is None or scan["data_status"] != "observed":
                totals["rules_not_evaluated"] += 1
                continue
            totals["candidate" if scan["engine_candidates"] else "no_candidate"] += 1
            totals["qa_disagreements"] += int(not scan["matches_engine"])
            for direction, setups in scan["setups"].items():
                for family, conditions in setups.items():
                    for name, condition in conditions.items():
                        if condition["passed"] is False:
                            failures[f"{direction} {family} {name}"] += 1
    return {"totals": dict(totals), "failed_condition_counts": dict(failures.most_common())}


if __name__ == "__main__":
    import argparse
    import time
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Summarize recorded Gold V2 entry checks")
    parser.add_argument("database", type=Path)
    parser.add_argument("--hours", type=float, default=24)
    args = parser.parse_args()
    print(json.dumps(summary(args.database, time.time()-args.hours*3600), indent=2))
