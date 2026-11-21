"""Public GET-only candle-source comparison for abnormal Delta India DEMO bars.

A trade-candle match to the same upstream feed is not independent evidence.
Compare five 1m traded candles, the 5m traded candle, and the 5m mark-price
candle at identical UTC times without changing the original history.
Never repair prices, alter the archive, or authorize an order.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json

from tradebot.delta import DeltaDemo, DEMO_API

MINUTE = 60
BAR = 300
MAX_TIMES = 20


class CandleReadError(ValueError):
    """Only fixed/sanitized diagnostic failure reasons."""


def _number(value):
    if type(value) not in (str, int, float, Decimal):
        raise CandleReadError("candle_numeric_field_unverified")
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise CandleReadError("candle_numeric_field_unverified") from None
    if not number.is_finite():
        raise CandleReadError("candle_numeric_field_unverified")
    return number


def _read(exchange, symbol, resolution, first, step, count):
    response = exchange._request(
        "GET", "/v2/history/candles", auth=False,
        params={"symbol": symbol, "resolution": resolution,
                "start": first, "end": first + step * count - 1},
    )
    if type(response) is not dict or type(response.get("result")) is not list:
        raise CandleReadError("candle_response_unavailable")
    rows = {}
    for raw in response["result"]:
        if type(raw) is not dict:
            raise CandleReadError("candle_response_malformed")
        t = raw.get("time")
        if type(t) is str and t.isdecimal():
            t = int(t)
        if type(t) is not int or t < first or t >= first + step * count:
            raise CandleReadError("candle_timestamp_unverified")
        if t % step or t in rows:
            raise CandleReadError("candle_duplicate_or_alignment_error")
        numbers = tuple(_number(raw.get(k)) for k in
                        ("open", "high", "low", "close", "volume"))
        o, h, l, c, v = numbers
        if not (o > 0 and l > 0 and l <= min(o, c)
                and h >= max(o, c) and v >= 0):
            raise CandleReadError("candle_ohlcv_invalid")
        rows[t] = numbers
    expected = [first + i * step for i in range(count)]
    if set(rows) != set(expected):
        raise CandleReadError("candle_window_incomplete")
    return [rows[t] for t in expected]


def _aggregate(minute_bars):
    return (minute_bars[0][0],
            max(row[1] for row in minute_bars),
            min(row[2] for row in minute_bars),
            minute_bars[-1][3],
            sum((row[4] for row in minute_bars), Decimal(0)))


def compare_sources(exchange, times):
    """Read-only cross-timeframe and mark comparison, NEVER release authority."""
    report = {
        "mode": "public_delta_demo_market_data_only",
        "trade_authorized": False,
        "safe_to_enable_fire": False,
        "ready_for_unattended_trading": False,
        "archive_mutations": False,
        "broker_order_mutations": False,
        "independent_price_validation": False,
        "status": "review_required",
        "results": [],
        "blockers": [],
    }
    if (getattr(exchange, "base_url", None) != DEMO_API
            or getattr(exchange, "allow_orders", None) is not False):
        report["blockers"] = ["read_only_demo_client_required"]
        return report
    if (type(times) not in (list, tuple) or not 1 <= len(times) <= MAX_TIMES
            or any(type(t) is not int or t <= 0 or t % BAR for t in times)
            or len(set(times)) != len(times)):
        report["blockers"] = ["invalid_candle_window"]
        return report
    for t in times:
        result = {
            "utc": datetime.fromtimestamp(t, timezone.utc).isoformat(),
            "comparison": "unverified",
            "source_checks": {},
        }
        # Each source is independently checked. A partial failure must never
        # be disguised as a successful cross-resolution comparison, but the
        # operator can now tell which public GET response is missing/malformed.
        # Fixed error codes only: do not leak provider response or URL details.
        sources = (
            ("trade_5m", "BTCUSD", "5m", BAR, 1),
            ("trade_1m", "BTCUSD", "1m", MINUTE, 5),
            ("mark_5m", "MARK:BTCUSD", "5m", BAR, 1),
        )
        readings = {}
        for name, symbol, resolution, step, count in sources:
            try:
                readings[name] = _read(exchange, symbol, resolution, t, step, count)
                result["source_checks"][name] = "complete"
            except CandleReadError as exc:
                code = str(exc)
                if code not in {
                    "candle_numeric_field_unverified",
                    "candle_response_unavailable",
                    "candle_response_malformed",
                    "candle_timestamp_unverified",
                    "candle_duplicate_or_alignment_error",
                    "candle_ohlcv_invalid",
                    "candle_window_incomplete",
                }:
                    code = "candle_source_unverified"
                result["source_checks"][name] = code
            except Exception:
                result["source_checks"][name] = "candle_source_unavailable"

        if len(readings) != len(sources):
            report["blockers"].append("candle_source_comparison_unverified")
        else:
            five = readings["trade_5m"][0]
            minutes = readings["trade_1m"]
            mark = readings["mark_5m"][0]
            aggregate = _aggregate(minutes)
            result.update({
                "comparison": "source_crosscheck_complete_not_independent_proof",
                "trade_5m_high": str(five[1]),
                "trade_5m_low": str(five[2]),
                "aggregated_1m_high": str(aggregate[1]),
                "aggregated_1m_low": str(aggregate[2]),
                "mark_5m_high": str(mark[1]),
                "mark_5m_low": str(mark[2]),
                "five_minute_ohlc_matches_one_minute": five[:4] == aggregate[:4],
                "five_minute_volume_matches_one_minute": five[4] == aggregate[4],
                "mark_reference_is_independent": False,
            })
            # A mismatch remains evidence for review, never a reason to relax
            # an existing suspicious_extreme or quarantine admission blocker.
            if five[:4] != aggregate[:4]:
                report["blockers"].append("cross_resolution_ohlc_mismatch")
        report["results"].append(result)
    report["blockers"] = sorted(set(report["blockers"]))
    if not report["blockers"]:
        report["status"] = "source_crosscheck_complete_review_still_required"
    return report


def _timestamp(value):
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError
        dt = dt.astimezone(timezone.utc)
        if dt.second or dt.microsecond or dt.minute % 5:
            raise ValueError
        return int(dt.timestamp())
    except (TypeError, ValueError, OverflowError):
        raise argparse.ArgumentTypeError("Use an aligned ISO-8601 UTC timestamp") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", action="append", type=_timestamp, required=True,
                        help="UTC 5m candle timestamp (repeat 1-20 times)")
    args = parser.parse_args(argv)
    report = compare_sources(DeltaDemo(allow_orders=False), args.at)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "source_crosscheck_complete_review_still_required" else 2


if __name__ == "__main__":
    raise SystemExit(main())
