"""Resumable Delta demo OHLCV history and point-in-time levels, in UTC."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import logging
import math
import sqlite3
import time

from tradebot.chart_desk import epoch
from tradebot.fire_market import SYMBOLS
from tradebot.market_integrity import suspect_candle_times, archive_extreme_suspicious

STEP = 300
PAGE = 1500 * STEP
DAY = 86400
LOG = logging.getLogger(__name__)


class CandleArchive:
    def __init__(self, path):
        self.path = path
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS candles(
                    symbol TEXT, t INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL,
                    PRIMARY KEY(symbol,t)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS coverage(
                    symbol TEXT PRIMARY KEY, floor INTEGER, oldest_scan INTEGER, newest_scan INTEGER);
                CREATE TABLE IF NOT EXISTS candle_quarantine(
                    symbol TEXT NOT NULL, t INTEGER NOT NULL,
                    o REAL, h REAL, l REAL, c REAL, v REAL,
                    reason TEXT NOT NULL, PRIMARY KEY(symbol,t));
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def sync_page(self, exchange, symbol, now):
        """Commit one historical page or forward catch-up together with its cursor."""
        end = int(now)//STEP*STEP
        with closing(self.connect()) as db:
            progress = db.execute("SELECT floor,oldest_scan,newest_scan FROM coverage WHERE symbol=?",
                                  (symbol,)).fetchone()
        if not progress:
            product = exchange._request("GET", "/v2/products/"+symbol)["result"]
            if product["symbol"] != symbol:
                raise ValueError("Unexpected history product")
            launched = epoch(product.get("launch_time"))
            floor = int(launched or 1230940800)//STEP*STEP
            if floor >= end:
                raise ValueError("Invalid product launch date")
            start, stop = max(floor, end-PAGE), end
        else:
            floor, oldest, newest = progress
            if end > newest:
                start, stop = max(floor, newest-12*STEP), min(end, newest+PAGE-12*STEP)
            elif oldest > floor:
                start, stop = max(floor, oldest-PAGE), oldest
            else:
                return False
        result = exchange._request("GET", "/v2/history/candles", params={
            "symbol": symbol, "resolution": "5m", "start": start, "end": stop-1})["result"]
        if not isinstance(result, list) or len(result) > 2000:
            raise ValueError("Malformed history page")
        records = []
        for row in result:
            t = int(row["time"])
            if not start <= t < stop:
                continue
            o,h,l,c,v = (float(row[k]) for k in ("open","high","low","close","volume"))
            if (t % STEP or not all(map(math.isfinite,(o,h,l,c,v))) or v < 0 or
                    not 0 < l <= min(o,c) <= max(o,c) <= h):
                raise ValueError("Malformed historical candle")
            records.append((symbol,t,o,h,l,c,v))
        # A broker history refetch may revise a previously closed candle.
        # Never silently overwrite its stored economics or treat a conflicting
        # duplicate in one response as a trusted replacement. Preserve the
        # FIRST stored original in quarantine and require human investigation.
        flagged = suspect_candle_times(records)
        incoming = {row[1]: row for row in records}
        with closing(self.connect()) as db, db:
            old_rows = db.execute(
                "SELECT symbol,t,o,h,l,c,v FROM candles "
                "WHERE symbol=? AND t>=? AND t<?", (symbol,start,stop)
            ).fetchall()
            original = {row[1]: row for row in old_rows}
            for stamp, row in incoming.items():
                if stamp in original and row != original[stamp]:
                    flagged[stamp] = "conflicting_historical_refetch"
            # A page-edge bar may only have one in-page neighbor. Include
            # previously archived adjacent bars as context, but only ever
            # quarantine incoming times (not unrelated historical context).
            boundary = db.execute(
                "SELECT symbol,t,o,h,l,c,v FROM candles WHERE symbol=? AND "
                "((t>=? AND t<?) OR (t>=? AND t<?))",
                (symbol,start-3*STEP,start,stop,stop+3*STEP)
            ).fetchall()
            corroborated = suspect_candle_times(records + boundary)
            for stamp, reason in corroborated.items():
                if stamp in incoming and stamp not in flagged:
                    flagged[stamp] = reason
            # Conflicting GET observations cannot be collapsed into the
            # latest candle. The first observed row remains the audit source.
            to_quarantine = [
                (*(original.get(row[1]) if row[1] in original
                   and flagged.get(row[1]) == "conflicting_historical_refetch"
                   else row), flagged[row[1]])
                for row in records if row[1] in flagged
            ]
            db.executemany(
                "INSERT OR IGNORE INTO candle_quarantine VALUES (?,?,?,?,?,?,?,?)",
                to_quarantine)
            db.executemany(
                "DELETE FROM candles WHERE symbol=? AND t=?",
                [(symbol,stamp) for stamp in flagged])
            # Immutable existing closed candles: identical refetches are
            # harmless; disputed prices are quarantined instead of replaced.
            db.executemany(
                "INSERT OR IGNORE INTO candles SELECT ?,?,?,?,?,?,? "
                "WHERE NOT EXISTS (SELECT 1 FROM candle_quarantine WHERE symbol=? AND t=?)",
                [(*row, row[0], row[1]) for row in records if row[1] not in flagged])
            db.execute("""INSERT INTO coverage VALUES (?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET
                       oldest_scan=min(oldest_scan,excluded.oldest_scan),
                       newest_scan=max(newest_scan,excluded.newest_scan)""",(symbol,floor,start,stop))
        return True

    def run(self, exchange, stopping):
        while not stopping.is_set():
            more = False
            for symbol in SYMBOLS:
                try:
                    more |= self.sync_page(exchange,symbol,time.time())
                except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error) as exc:
                    LOG.warning("Candle sync %s: %s", symbol, type(exc).__name__)
                    stopping.wait(4)
            stopping.wait(1 if more else 15)

    def levels(self, symbol, at, price):
        end = int(at)//STEP*STEP
        day = datetime.fromtimestamp(end, timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
        week = day-timedelta(days=day.weekday())
        month = day.replace(day=1)
        previous_month = (month-timedelta(days=1)).replace(day=1)
        windows = {"day":(day,None),"previous_day":(day-timedelta(days=1),day),
                   "week":(week,None),"previous_week":(week-timedelta(days=7),week),
                   "month":(month,None),"previous_month":(previous_month,month)}
        periods = {}
        with closing(self.connect()) as db:
            coverage = db.execute("SELECT floor,oldest_scan,newest_scan FROM coverage WHERE symbol=?",
                                  (symbol,)).fetchone()
            for key,(a,b) in windows.items():
                start = int(a.timestamp())
                stop = int(b.timestamp()) if b else end
                count,hi,lo = db.execute("SELECT count(*),max(h),min(l) FROM candles "
                    "WHERE symbol=? AND t>=? AND t<?",(symbol,start,stop)).fetchone()
                expected = (stop-start)//STEP
                complete = count > 0 and count == expected
                quarantined = db.execute(
                    "SELECT count(*) FROM candle_quarantine WHERE symbol=? AND t>=? AND t<?",
                    (symbol,start,stop)).fetchone()[0]
                suspicious = complete and archive_extreme_suspicious(
                    db, symbol, start, stop)
                status = ("quarantined" if quarantined else
                          "suspicious_extreme" if suspicious else
                          "provisionally_valid" if complete else "incomplete")
                usable = complete and not quarantined and not suspicious
                periods[key] = {"high":hi if usable else None,
                                "low":lo if usable else None,
                                "bars":count,"expected":expected,
                                "quarantined_bars":quarantined,
                                "quality_status":status}
            bars = db.execute("SELECT t,h,l FROM candles WHERE symbol=? AND t>=? AND t<? ORDER BY t",
                              (symbol,end-7*DAY,end)).fetchall()
        return {"as_of":end,"resolution":"5m","timezone":"UTC","periods":periods,
                "scan_from":coverage[1] if coverage else None,
                "scanned_to_launch":bool(coverage and coverage[0]==coverage[1]),
                "swings":swing_levels(bars,price)}


def swing_levels(bars, price):
    """Nearest confirmed extrema over seven days. Require two closed bars on each side."""
    swings = {}
    for label,span in (("15m",900),("1h",3600)):
        buckets = {}
        for t,h,l in bars:
            buckets.setdefault(t//span*span,[]).append((h,l))
        full = {t:(max(h for h,l in rows),min(l for h,l in rows)) for t,rows in buckets.items()
                if len(rows)==span//STEP}
        support = resistance = None
        for t,(hi,lo) in full.items():
            neighbors = [full.get(t+i*span) for i in (-2,-1,1,2)]
            if not all(neighbors):
                continue
            if lo < price and all(lo<n[1] for n in neighbors) and (not support or lo>=support["price"]):
                support = {"price":lo,"pivot_at":t,"confirmed_at":t+3*span}
            if hi > price and all(hi>n[0] for n in neighbors) and (not resistance or hi<=resistance["price"]):
                resistance = {"price":hi,"pivot_at":t,"confirmed_at":t+3*span}
        swings[label] = {"support":support,"resistance":resistance}
    return swings
