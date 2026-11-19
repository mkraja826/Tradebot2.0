"""Resumable Delta demo OHLCV history and point-in-time levels, in UTC."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import logging
import math
import sqlite3
import time

from tradebot.chart_desk import epoch
from tradebot.fire_market import SYMBOLS

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
        with closing(self.connect()) as db, db:
            db.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?)", records)
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
                periods[key] = {"high":hi if complete else None,"low":lo if complete else None,
                                "bars":count,"expected":expected}
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
