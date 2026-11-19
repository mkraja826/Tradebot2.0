"""Triage suspect 5-minute historical extremes without discarding originals."""
from math import isfinite
from statistics import median


def suspect_candle_times(records, *, step=300, deviation=0.60):
    """Return suspicious timestamps for a single symbol and timeframe.

    A dislocation is an INVESTIGATION flag, not proof the market data was bad.
    Reference prices come from neighboring historical candles, not today's spot.
    """
    seen = {}
    flags = {}
    for row in records:
        symbol, stamp, opened, high, low, close, volume = row
        if (type(stamp) is not int or stamp % step or
                not all(isfinite(float(v)) for v in (opened, high, low, close, volume)) or
                not 0 < low <= min(opened, close) <= max(opened, close) <= high or volume < 0):
            raise ValueError("Malformed historical candle")
        if stamp in seen and seen[stamp] != row:
            flags[stamp] = "conflicting_duplicate"
        else:
            seen[stamp] = row
    for stamp, row in seen.items():
        nearby = [seen[stamp + offset * step][5] for offset in (-3, -2, -1, 1, 2, 3)
                  if stamp + offset * step in seen
                  and stamp + offset * step not in flags]
        if stamp in flags or len(nearby) < 2:
            continue
        anchor = median(nearby)
        if anchor <= 0:
            flags[stamp] = "invalid_neighbor_reference"
        elif row[4] < anchor * (1 - deviation) or row[3] > anchor * (1 + deviation):
            flags[stamp] = "extreme_neighbor_dislocation"
    return flags


def archive_extreme_suspicious(db, symbol, start, stop):
    """Check extrema imported before anomaly quarantine was available."""
    for ordering in ("h DESC", "l ASC"):
        extreme = db.execute(
            "SELECT t FROM candles WHERE symbol=? AND t>=? AND t<? ORDER BY " +
            ordering + " LIMIT 1", (symbol, start, stop)).fetchone()
        if extreme is None:
            continue
        stamp = extreme[0]
        nearby = db.execute(
            "SELECT symbol,t,o,h,l,c,v FROM candles "
            "WHERE symbol=? AND t>=? AND t<=? ORDER BY t",
            (symbol, stamp - 900, stamp + 900)).fetchall()
        if stamp in suspect_candle_times(nearby):
            return True
    return False
