"""GET-free, SQLite read-only 24-hour BTC DEMO history proposal.

This is not a replacement for six-period FIRE history or independent trade
price validation. It checks an explicitly bounded strategy input option
for a *future*, separately implemented supervised one-attempt pilot.
The original monthly extremes and quarantine remain preserved.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from tradebot.candle_archive import STEP
from tradebot.market_integrity import suspect_candle_times
from tradebot.fire_indicators import indicators

WINDOW_BARS = 288
NEIGHBOR_BARS = 3


def inspect_recent_btc_window(data_dir, *, now=None):
    result = {
        "mode": "read_only_btc_recent24h_candidate",
        "symbol": "BTCUSD",
        "source": "original_delta_demo_5m_archive",
        "status": "blocked",
        "reason": "original_archive_unavailable",
        "required_bars": WINDOW_BARS,
        "retained_bars": None,
        "quarantined_bars": None,
        "suspect_bars": None,
        "first_utc": None,
        "last_utc": None,
        "complete_contiguous_24h": False,
        "independently_verified_btc_perpetual_prices": False,
        "monthly_anomalies_excluded_from_proposed_input": True,
        "original_monthly_anomalies_resolved": False,
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "original_archive_mutations": False,
        "broker_order_mutations": False,
        "ai_calls": 0,
    }
    instant = now or datetime.now(timezone.utc)
    if (not isinstance(instant, datetime) or instant.tzinfo is None
            or instant.utcoffset() is None):
        result["reason"] = "utc_clock_required"
        return result
    stamp = int(instant.timestamp())
    end = (stamp // STEP) * STEP
    start = end - WINDOW_BARS * STEP
    if start <= 0:
        result["reason"] = "untrusted_window"
        return result
    root = Path(data_dir)
    path = root / "delta-demo-candles.sqlite"
    if (not root.is_dir() or root.is_symlink() or
            not path.is_file() or path.is_symlink()):
        return result
    try:
        with closing(sqlite3.connect(
                path.absolute().as_uri() + "?mode=ro",
                uri=True, timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise ValueError("archive_integrity_unverified")
            names = {name for (name,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"candles", "candle_quarantine", "coverage"} <= names:
                raise ValueError("original_archive_schema_unverified")
            coverage = db.execute(
                "SELECT newest_scan FROM coverage WHERE symbol='BTCUSD'"
            ).fetchone()
            if (coverage is None or type(coverage[0]) is not int
                    or coverage[0] < end):
                result["reason"] = "recent_archive_collection_not_current"
                return result
            quarantined = db.execute(
                "SELECT count(*) FROM candle_quarantine "
                "WHERE symbol='BTCUSD' AND t>=? AND t<?",
                (start, end)).fetchone()[0]
            rows = db.execute(
                "SELECT symbol,t,o,h,l,c,v FROM candles "
                "WHERE symbol='BTCUSD' AND t>=? AND t<? ORDER BY t",
                (start - NEIGHBOR_BARS * STEP, end)).fetchall()
            retained = [row for row in rows if row[1] >= start]
            result["retained_bars"] = len(retained)
            result["quarantined_bars"] = quarantined
            if len(retained) != WINDOW_BARS or any(
                    row[1] != start + i * STEP
                    for i, row in enumerate(retained)):
                result["reason"] = "missing_or_misaligned_recent_5m_bars"
                return result
            if quarantined != 0:
                result["reason"] = "recent_btc_quarantine_present"
                return result
            anomalies = suspect_candle_times(rows)
            suspect_count = sum(start <= t < end for t in anomalies)
            result["suspect_bars"] = suspect_count
            if suspect_count:
                result["reason"] = "recent_btc_price_dislocation"
                return result
            db.rollback()
        result["first_utc"] = datetime.fromtimestamp(
            start, timezone.utc).isoformat()
        result["last_utc"] = datetime.fromtimestamp(
            end - STEP, timezone.utc).isoformat()
        result["complete_contiguous_24h"] = True
        result["status"] = "recent24h_local_candidate_only"
        result["reason"] = "requires_independent_trade_price_and_broker_gates"
        return result
    except (sqlite3.Error, ValueError, TypeError, OverflowError, OSError):
        result["reason"] = "original_archive_integrity_or_schema_unverified"
        return result


def load_recent24h_strategy_context(data_dir, *, at, price):
    """Build true bounded BTC indicators and high/low with no month inputs.

    Double-check the actual 288 rows inside this single final read-only
    transaction, rather than treating a separately reported status as a
    trade permit. This is local archive evidence, not external trade proof.
    """
    report = inspect_recent_btc_window(data_dir, now=at)
    if report["status"] != "recent24h_local_candidate_only":
        raise ValueError("recent_btc_strategy_history_unverified")
    end = (int(at.timestamp()) // STEP) * STEP
    start = end - WINDOW_BARS * STEP
    path = Path(data_dir) / "delta-demo-candles.sqlite"
    with closing(sqlite3.connect(
            path.absolute().as_uri() + "?mode=ro", uri=True,
            timeout=3)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
            raise ValueError("recent_btc_archive_invalid")
        quarantine = db.execute(
            "SELECT count(*) FROM candle_quarantine "
            "WHERE symbol='BTCUSD' AND t>=? AND t<?",
            (start, end)).fetchone()[0]
        coverage = db.execute(
            "SELECT newest_scan FROM coverage WHERE symbol='BTCUSD'"
        ).fetchone()
        rows = db.execute(
            "SELECT symbol,t,o,h,l,c,v FROM candles "
            "WHERE symbol='BTCUSD' AND t>=? AND t<? ORDER BY t",
            (start - NEIGHBOR_BARS * STEP, end)).fetchall()
        valid = [v for v in rows if v[1] >= start]
        if (quarantine != 0 or not coverage or coverage[0] < end
                or len(valid) != WINDOW_BARS
                or any(v[1] != start + i*STEP for i,v in enumerate(valid))
                or any(start <= t < end for t in suspect_candle_times(rows))):
            raise ValueError("recent_btc_archive_changed_or_invalid")
        high = max(v[3] for v in valid)
        low = min(v[4] for v in valid)
        provider_rows = [
            {"time": t, "high": h, "low": l, "close": close, "volume": vol}
            for _, t, opened, h, l, close, vol in valid
        ]
        db.rollback()
    features = indicators(provider_rows, at.timestamp(), float(price))
    # Only point-in-time indicators based on locally verified 24h bars
    # enter GPT-6, never stale month highs or unverified previous-fill PnL.
    if (features.get("ema_15m") is None
            or features.get("ema_1h") is None
            or features.get("atr_5m") is None):
        raise ValueError("recent_btc_strategy_indicators_incomplete")
    levels = {
        "source": "original_delta_demo_24h_5m_local_only",
        "strategy_history_version": "btc-demo-recent24h-v1",
        "as_of": end, "resolution": "5m", "timezone": "UTC",
        "independent_price_validation": False,
        "periods": {
            "last_24h": {
                "high": high, "low": low, "bars": WINDOW_BARS,
                "expected": WINDOW_BARS, "quality_status": "provisionally_valid",
            }
        },
    }
    return features, levels


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)
    print(json.dumps(inspect_recent_btc_window(args.data_dir),
                     sort_keys=True, separators=(",", ":")))
    return 2  # A local data subset cannot authorize a broker order.


if __name__ == "__main__":
    raise SystemExit(main())
