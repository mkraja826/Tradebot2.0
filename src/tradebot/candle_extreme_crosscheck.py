"""GET-only, bounded cross-venue context for suspicious archived BTC extremes.

This reads the already-existing Delta DEMO candle archive and compares exact
historic UTC buckets with public Delta 1m/5m/mark and Coinbase BTC-USD spot.
Neither spot prices nor a duplicate Delta feed prove a perpetual trade print.
No auto-repair, archive writes, orders, funding changes, or release authority.
"""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from tradebot.delta import DEMO_API, DeltaDemo
from tradebot.independent_spot_triage import inspect_external_spot_context
from tradebot.market_integrity import suspect_candle_times

BAR = 300
MAX_CANDIDATES = 4
EXTREMES_PER_SIDE = 4


def _base():
    return {
        "environment": "delta-india-demo",
        "mode": "read_only_archive_cross_venue_context",
        "status": "blocked",
        "reason": "not_started",
        "candidate_count": 0,
        "selected_count": 0,
        "candidate_examples_truncated": False,
        "timestamps_utc": [],
        "cross_venue_report": None,
        "independent_perpetual_price_proven": False,
        "quarantine_release_authorized": False,
        "archive_mutations": False,
        "broker_order_mutations": False,
        "ledger_mutations": False,
        "ai_calls": 0,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "ready_for_unattended_trading": False,
    }


def _periods(at):
    """Current partial and previous complete UTC month, closed 5m bars only."""
    end = int(at.timestamp()) // BAR * BAR
    month = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous = (month - timedelta(days=1)).replace(day=1)
    return ((int(previous.timestamp()), int(month.timestamp())),
            (int(month.timestamp()), end))


def _suspicious_extreme_times(db, start, end):
    """Target extreme highs/lows using the archive's own anomaly heuristic.

    This is a bounded investigation of top/bottom extrema, not an exhaustive
    anomaly inventory or independent market-data attestation.
    """
    if end <= start:
        return set()
    stamps = set()
    for order in ("h DESC,t ASC", "l ASC,t ASC"):
        stamps.update(row[0] for row in db.execute(
            "SELECT t FROM candles WHERE symbol='BTCUSD' AND t>=? AND t<? "
            "ORDER BY " + order + " LIMIT ?",
            (start, end, EXTREMES_PER_SIDE)))
    suspected = set()
    for stamp in stamps:
        neighbors = db.execute(
            "SELECT symbol,t,o,h,l,c,v FROM candles "
            "WHERE symbol='BTCUSD' AND t>=? AND t<=? ORDER BY t",
            (stamp-3*BAR, stamp+3*BAR)).fetchall()
        if stamp in suspect_candle_times(neighbors):
            suspected.add(stamp)
    return suspected


def inspect_archive_extremes(data_dir, *, now=None,
                             max_candidates=MAX_CANDIDATES):
    """Inspect existing SQLite using one consistent transaction, no writes."""
    out = _base()
    if type(max_candidates) is not int or not 1 <= max_candidates <= MAX_CANDIDATES:
        out["reason"] = "invalid_candidate_limit"
        return out
    at = datetime.now(timezone.utc) if now is None else now
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        out["reason"] = "invalid_utc_clock"
        return out
    at = at.astimezone(timezone.utc)
    root = Path(data_dir)
    archive = root / "delta-demo-candles.sqlite"
    if (not root.is_dir() or root.is_symlink() or not archive.is_file()
            or archive.is_symlink()):
        out["reason"] = "trusted_original_archive_required"
        return out
    try:
        with closing(sqlite3.connect(
            archive.absolute().as_uri() + "?mode=ro", uri=True, timeout=5
        )) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise ValueError("invalid_archive_integrity")
            tables = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"candles", "candle_quarantine", "coverage"} <= tables:
                raise ValueError("missing_archive_schema")
            candidates_by_period = [
                sorted(_suspicious_extreme_times(db, start, end))
                for start, end in _periods(at)
            ]
            db.rollback()
    except (sqlite3.Error, ValueError, TypeError, OverflowError, OSError):
        out["reason"] = "read_only_archive_evidence_unavailable"
        return out
    all_candidates = set().union(*candidates_by_period)
    out["candidate_count"] = len(all_candidates)
    # Interleave prior/current months so one anomalous period cannot starve
    # the other from bounded public source queries.
    picked = []
    while len(picked) < max_candidates and any(candidates_by_period):
        for group in candidates_by_period:
            if group and len(picked) < max_candidates:
                picked.append(group.pop(0))
    out["selected_count"] = len(picked)
    out["candidate_examples_truncated"] = len(all_candidates) > len(picked)
    out["timestamps_utc"] = [
        datetime.fromtimestamp(t, timezone.utc).isoformat() for t in picked
    ]
    out["_candidate_times"] = picked  # Removed before the public report.
    out["reason"] = ("suspicious_extreme_candidates_found" if picked
                     else "no_candidate_extreme_not_market_validation")
    return out


def crosscheck_archive_extremes(
        data_dir, *, now=None, max_candidates=MAX_CANDIDATES,
        exchange=None, spot_reader=None,
        context_check=inspect_external_spot_context):
    """Compare up to four exact suspect buckets via fixed GET-only sources."""
    report = inspect_archive_extremes(
        data_dir, now=now, max_candidates=max_candidates)
    times = report.pop("_candidate_times", [])
    if report["reason"] != "suspicious_extreme_candidates_found":
        return report
    if exchange is None:
        exchange = DeltaDemo(allow_orders=False)
    if (getattr(exchange, "base_url", None) != DEMO_API
            or getattr(exchange, "allow_orders", None) is not False):
        report["reason"] = "read_only_demo_client_required"
        return report
    try:
        kwargs = {} if spot_reader is None else {"spot_reader": spot_reader}
        details = context_check(exchange, times, **kwargs)
        if not isinstance(details, dict):
            raise ValueError("invalid crossvenue report")
        # Safe projection, no broker payloads or local financial context.
        report["cross_venue_report"] = {
            "status": details.get("status"),
            "blockers": details.get("blockers"),
            "results": details.get("results"),
            "independent_price_validation": False,
            "perpetual_trade_print_verified": False,
            "quarantine_release_authorized": False,
            "safe_to_enable_fire": False,
            "trade_authorized": False,
        }
        report["reason"] = ("cross_venue_context_available_for_independent_review"
                            if details.get("blockers") == []
                            else "cross_venue_context_incomplete_or_dislocated")
    except Exception:
        report["reason"] = "cross_venue_observation_unavailable"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--max-candidates", type=int, default=MAX_CANDIDATES)
    args = parser.parse_args(argv)
    report = crosscheck_archive_extremes(
        args.data_dir, max_candidates=args.max_candidates)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    # Source agreement is not independent perpetual-print verification.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
