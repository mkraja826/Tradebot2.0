"""Read-only local archive evidence for suspicious/missing DEMO 5m candles.

Only identifies timestamps and quality blockers; never releases quarantine,
repairs bars, computes replacement prices, invokes models, or authorizes FIRE.
"""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from tradebot.candle_archive import STEP
from tradebot.market_integrity import suspect_candle_times

MAX_EXAMPLES = 8


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def inspect_window(db, symbol, start, stop):
    """Find actual missing timestamps, quarantines, and neighbor anomalies."""
    if (symbol not in ("BTCUSD", "XAUTUSD") or type(start) is not int
            or type(stop) is not int or stop <= start or start % STEP
            or stop % STEP or stop-start > 32*86400):
        raise ValueError("invalid_bounded_archive_window")
    # Three adjacent bars from the same stored archive are only contextual
    # observations, not independent verification of an extreme broker print.
    rows = db.execute(
        "SELECT symbol,t,o,h,l,c,v FROM candles WHERE symbol=? "
        "AND t>=? AND t<? ORDER BY t",
        (symbol, start - 3*STEP, stop + 3*STEP)
    ).fetchall()
    retained = {row[1] for row in rows if start <= row[1] < stop}
    quarantined_rows = db.execute(
        "SELECT t,reason FROM candle_quarantine WHERE symbol=? AND t>=? "
        "AND t<? ORDER BY t", (symbol, start, stop)
    ).fetchall()
    quarantined = {r[0] for r in quarantined_rows}
    expected = (stop - start) // STEP
    missing = [t for t in range(start, stop, STEP)
               if t not in retained and t not in quarantined]
    flagged = suspect_candle_times(rows)
    suspects = sorted(t for t in flagged if start <= t < stop)
    issues = []
    if missing:
        issues.append("missing_broker_bars")
    if quarantined:
        issues.append("quarantined_evidence")
    if suspects:
        issues.append("suspicious_neighbor_extreme")
    return {
        "expected_bars": expected,
        "retained_bars": len(retained),
        "missing_bar_count": len(missing),
        "missing_utc_examples": [_iso(t) for t in missing[:MAX_EXAMPLES]],
        "quarantined_bar_count": len(quarantined),
        "quarantined_utc_examples": [_iso(t) for t in sorted(quarantined)[:MAX_EXAMPLES]],
        "suspect_bar_count": len(suspects),
        "suspect_utc_examples": [_iso(t) for t in suspects[:MAX_EXAMPLES]],
        "examples_truncated": {
            "missing": len(missing) > MAX_EXAMPLES,
            "quarantined": len(quarantined) > MAX_EXAMPLES,
            "suspect": len(suspects) > MAX_EXAMPLES,
        },
        "issues": issues,
        "quality_status": "blocked" if issues else "provisionally_complete_not_independently_verified",
    }


def inventory_archive(data_dir, *, now=None):
    """Consistent SQLite ro snapshot for the current and previous UTC month."""
    report = {
        "mode": "local_archive_read_only",
        "source": "existing_delta_demo_five_minute_archive",
        "status": "blocked",
        "periods": {},
        "blockers": [],
        "ledger_mutations": False,
        "archive_mutations": False,
        "broker_order_mutations": False,
        "ai_calls": 0,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "ready_for_unattended_trading": False,
        "independent_market_verification": False,
    }
    instant = now or datetime.now(timezone.utc)
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        report["blockers"].append("trusted_utc_clock_required")
        return report
    instant = instant.astimezone(timezone.utc)
    end = int(instant.timestamp()) // STEP * STEP
    month = instant.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous = (month - timedelta(days=1)).replace(day=1)
    windows = (("month", int(month.timestamp()), end),
               ("previous_month", int(previous.timestamp()), int(month.timestamp())))
    root = Path(data_dir)
    dbpath = root / "delta-demo-candles.sqlite"
    if (not root.is_dir() or root.is_symlink() or
            not dbpath.is_file() or dbpath.is_symlink()):
        report["blockers"].append("original_archive_missing_or_untrusted")
        return report
    try:
        with closing(sqlite3.connect(
            dbpath.absolute().as_uri() + "?mode=ro", uri=True, timeout=5
        )) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise ValueError("archive_integrity_unverified")
            required = {"candles", "candle_quarantine", "coverage"}
            present = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not required <= present:
                raise ValueError("archive_schema_unverified")
            for symbol in ("BTCUSD", "XAUTUSD"):
                for name, start, stop in windows:
                    result = inspect_window(db, symbol, start, stop)
                    report["periods"][symbol + "_" + name] = result
                    for issue in result["issues"]:
                        report["blockers"].append(
                            symbol.lower() + "_" + name + "_" + issue)
            db.rollback()
    except (sqlite3.Error, ValueError, TypeError, OverflowError, OSError):
        report["periods"] = {}
        report["blockers"] = ["original_archive_evidence_unavailable"]
        return report
    report["blockers"] = sorted(set(report["blockers"]))
    report["status"] = ("local_archive_issues_identified" if report["blockers"]
                        else "archive_windows_provisionally_complete")
    # An apparently complete Delta archive remains NOT an independent venue
    # price attestation and never authorizes a new trade.
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)
    report = inventory_archive(args.data_dir)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "archive_windows_provisionally_complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
