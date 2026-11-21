"""Read-only *independent-venue spot* context for suspect Delta DEMO BTC candles.

Compare Delta's same-source traded 5m/1m/mark series to the PUBLIC Coinbase
Exchange BTC-USD SPOT 5-minute candle at exactly the same UTC timestamp.
Coinbase spot is a different instrument from Delta BTCUSD perpetual, and
CANNOT independently verify a Delta perpetual trade/print, authorize FIRE,
release quarantined data, or provide replacement archive prices.

No credentials, SQLite access, file writes, order access or paid API calls.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from urllib import error, parse, request

from tradebot.candle_source_diagnostic import (
    BAR, CandleReadError, _number, _timestamp, compare_sources,
)
from tradebot.delta import DeltaDemo

COINBASE_API = "https://api.exchange.coinbase.com"
MAX_RESPONSE_BYTES = 16_384


class IndependentSpotError(ValueError):
    """Fixed diagnostic codes; no remote response bodies or URL errors."""


class _NoRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise IndependentSpotError("external_spot_redirect_refused")


def read_coinbase_spot(utc_at):
    """Fetch exactly one closed historic BTC-USD spot bar, GET-only."""
    if type(utc_at) is not int or utc_at <= 0 or utc_at % BAR:
        raise IndependentSpotError("external_spot_timestamp_invalid")
    start = datetime.fromtimestamp(utc_at, timezone.utc)
    stop = datetime.fromtimestamp(utc_at + BAR, timezone.utc)
    query = parse.urlencode({
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": stop.isoformat().replace("+00:00", "Z"),
        "granularity": BAR,
    })
    endpoint = COINBASE_API + "/products/BTC-USD/candles?" + query
    opener = request.build_opener(_NoRedirects())
    req = request.Request(endpoint, method="GET",
                          headers={"Accept": "application/json",
                                   "User-Agent": "Tradebot2-BTC-Safety-Triage/1"})
    try:
        with opener.open(req, timeout=8) as response:
            if response.status != 200:
                raise IndependentSpotError("external_spot_http_unverified")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise IndependentSpotError("external_spot_response_oversized")
        data = json.loads(raw)
    except IndependentSpotError:
        raise
    except (error.HTTPError, error.URLError, TimeoutError, OSError, ValueError,
            TypeError, OverflowError):
        raise IndependentSpotError("external_spot_unavailable") from None

    # Coinbase Exchange public candles: [time, low, high, open, close, volume].
    # Request windows can include an additional edge bucket; reject duplicates
    # and do not borrow a nearby bar if the exact target bar is unavailable.
    if type(data) is not list or not 1 <= len(data) <= 3:
        raise IndependentSpotError("external_spot_response_invalid")
    matched = []
    for row in data:
        if type(row) not in (list, tuple) or len(row) != 6:
            raise IndependentSpotError("external_spot_response_invalid")
        t, low, high, opened, close, volume = row
        if type(t) is not int or t % BAR:
            raise IndependentSpotError("external_spot_timestamp_invalid")
        if t == utc_at:
            try:
                l, h, o, c, v = tuple(_number(val) for val in
                                     (low, high, opened, close, volume))
            except CandleReadError:
                raise IndependentSpotError("external_spot_numeric_invalid") from None
            if not (o > 0 and l > 0 and l <= min(o, c)
                    and h >= max(o, c) and v >= 0):
                raise IndependentSpotError("external_spot_ohlcv_invalid")
            matched.append((l, h, o, c, v))
        elif t not in (utc_at - BAR, utc_at + BAR):
            raise IndependentSpotError("external_spot_timestamp_invalid")
    if len(matched) != 1:
        raise IndependentSpotError("external_spot_target_missing_or_duplicated")
    low, high, opened, close, volume = matched[0]
    return {
        "low": low, "high": high, "open": opened, "close": close,
        "volume": volume,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
    }


def inspect_external_spot_context(exchange, times, *, spot_reader=read_coinbase_spot):
    """One independent market REFERENCE only; deterministic no-trade output."""
    report = compare_sources(exchange, times)
    report["independent_market_context"] = "coinbase_exchange_btc_usd_spot"
    report["perpetual_trade_print_verified"] = False
    report["independent_price_validation"] = False
    report["quarantine_release_authorized"] = False
    report["safe_to_enable_fire"] = False
    report["trade_authorized"] = False
    report["ready_for_unattended_trading"] = False
    report["archive_mutations"] = False
    report["broker_order_mutations"] = False

    if report["blockers"] in (["read_only_demo_client_required"],
                              ["invalid_candle_window"]):
        return report

    for t, entry in zip(times, report["results"]):
        try:
            spot = spot_reader(t)
        except IndependentSpotError as exc:
            entry["coinbase_spot_check"] = exc.code if exc.code in {
                "external_spot_timestamp_invalid",
                "external_spot_redirect_refused",
                "external_spot_http_unverified",
                "external_spot_response_oversized",
                "external_spot_response_invalid",
                "external_spot_numeric_invalid",
                "external_spot_ohlcv_invalid",
                "external_spot_target_missing_or_duplicated",
                "external_spot_unavailable",
            } else "external_spot_unverified"
            report["blockers"].append("external_spot_context_unavailable")
            continue
        except Exception:
            entry["coinbase_spot_check"] = "external_spot_unavailable"
            report["blockers"].append("external_spot_context_unavailable")
            continue

        entry.update({
            "coinbase_spot_check": "complete",
            "coinbase_spot_product": "BTC-USD spot (not Delta perpetual)",
            "coinbase_spot_high": str(spot["high"]),
            "coinbase_spot_low": str(spot["low"]),
            "coinbase_spot_close": str(spot["close"]),
            "coinbase_public_response_sha256": spot["response_sha256"],
            "spot_is_same_instrument_as_delta_perpetual": False,
        })
        if entry["comparison"] != "source_crosscheck_complete_not_independent_proof":
            entry["cross_venue_observation"] = "delta_source_incomplete"
            continue
        try:
            delta_low = _number(entry["trade_5m_low"])
            delta_high = _number(entry["trade_5m_high"])
            spot_low = _number(spot["low"])
            spot_high = _number(spot["high"])
            low_ratio = delta_low / spot_low
            high_ratio = delta_high / spot_high
        except (KeyError, CandleReadError, ZeroDivisionError, TypeError):
            entry["cross_venue_observation"] = "comparison_unverified"
            report["blockers"].append("cross_venue_comparison_unverified")
            continue

        entry["delta_perpetual_low_to_coinbase_spot_low"] = str(low_ratio)
        entry["delta_perpetual_high_to_coinbase_spot_high"] = str(high_ratio)
        # A large dislocation is a manual-review alarm, not a license
        # to replace the DEMO perpetual candle with spot data.
        extreme = (low_ratio < Decimal("0.4") or high_ratio > Decimal("1.6"))
        entry["cross_venue_observation"] = (
            "extreme_cross_venue_dislocation_review_required" if extreme
            else "spot_context_only_perpetual_trade_unverified")
        if extreme:
            report["blockers"].append("extreme_cross_venue_dislocation")

    report["blockers"] = sorted(set(report["blockers"]))
    # A successful public spot cross-check is never evidence that the
    # DELTA DEMO perpetual candle is authentic; leave safe flags false.
    if (len(report["results"]) == len(times) and not report["blockers"]
            and all(item.get("coinbase_spot_check") == "complete"
                    for item in report["results"])):
        report["status"] = "cross_venue_spot_context_complete_manual_review_required"
    else:
        report["status"] = "cross_venue_review_blocked"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", action="append", type=_timestamp,
                        required=True, help="Aligned historic UTC 5m timestamp")
    args = parser.parse_args(argv)
    result = inspect_external_spot_context(
        DeltaDemo(allow_orders=False), args.at)
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == (
        "cross_venue_spot_context_complete_manual_review_required") else 2


if __name__ == "__main__":
    raise SystemExit(main())
