"""Public spot venue sanity check; never certifies Delta perpetual trade prints."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from urllib import request, error

URL = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
MAX_BODY = 4096
MAX_AGE_SECONDS = 30
MAX_FUTURE_SECONDS = 5
MAX_SPOT_SPREAD_BPS = Decimal("20")
MAX_DELTA_SPOT_DEVIATION_BPS = Decimal("150")


class PublicReferenceRejected(ValueError):
    """Fixed reason codes; never expose upstream content."""


class NoRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PublicReferenceRejected("public_reference_redirect_refused")


def number(value):
    try:
        if type(value) not in (int, float, str):
            raise ValueError
        n = Decimal(str(value))
        if n <= 0 or not n.is_finite():
            raise ValueError
        return n
    except (ValueError, InvalidOperation, TypeError):
        raise PublicReferenceRejected("public_reference_numeric_invalid") from None


def read_coinbase_spot():
    """Bounded keyless GET of one public Coinbase BTC-USD spot ticker."""
    req = request.Request(
        URL, method="GET", headers={"Accept": "application/json",
                                    "User-Agent": "Tradebot2-BTC-Reference/1"})
    try:
        with request.build_opener(NoRedirects()).open(req, timeout=5) as r:
            if r.status != 200:
                raise PublicReferenceRejected("public_reference_unavailable")
            body = r.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise PublicReferenceRejected("public_reference_oversized")
        value = json.loads(body)
        if type(value) is not dict:
            raise PublicReferenceRejected("public_reference_schema_invalid")
        return {"source": "coinbase_exchange_btc_usd_spot",
                "bid": str(number(value["bid"])),
                "ask": str(number(value["ask"])),
                "observed_at": value["time"]}
    except PublicReferenceRejected:
        raise
    except (error.HTTPError, error.URLError, TimeoutError, OSError,
            ValueError, KeyError, TypeError, UnicodeError):
        raise PublicReferenceRejected("public_reference_unavailable") from None


def corroborate_delta_quote(snapshot, spot, *, now=None):
    """Fail closed on stale/divergent spot; never claim perp verification."""
    if type(snapshot) is not dict or type(spot) is not dict:
        raise PublicReferenceRejected("public_reference_schema_invalid")
    if (spot.get("source") != "coinbase_exchange_btc_usd_spot"
            or set(spot) != {"source", "bid", "ask", "observed_at"}):
        raise PublicReferenceRejected("public_reference_schema_invalid")
    try:
        core = snapshot["core"]
        ticker = core["ticker"]
        if ticker["symbol"] != "BTCUSD":
            raise PublicReferenceRejected("public_reference_wrong_market")
        delta_mark = number(ticker["mark_price"])
        bid = number(spot["bid"])
        ask = number(spot["ask"])
        if ask < bid:
            raise PublicReferenceRejected("public_reference_crossed_quote")
        timestamp = spot["observed_at"]
        if type(timestamp) is not str or len(timestamp) > 48:
            raise ValueError
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        instant = now if now is not None else datetime.now(timezone.utc)
        if observed.tzinfo is None or instant.tzinfo is None:
            raise ValueError
        age = (instant - observed).total_seconds()
        if not -MAX_FUTURE_SECONDS <= age <= MAX_AGE_SECONDS:
            raise PublicReferenceRejected("public_reference_stale")
        midpoint = (bid + ask) / 2
        spread = (ask - bid) / midpoint * 10000
        if spread > MAX_SPOT_SPREAD_BPS:
            raise PublicReferenceRejected("public_reference_spread_wide")
        deviation = abs(delta_mark - midpoint) / midpoint * 10000
        if deviation > MAX_DELTA_SPOT_DEVIATION_BPS:
            raise PublicReferenceRejected("public_reference_dislocated")
        return {"status": "spot_reference_corroborated",
                "source": "coinbase_exchange_btc_usd_spot",
                "delta_spot_deviation_bps": str(deviation.quantize(Decimal("0.001"))),
                "independent_perpetual_trade_print_verified": False,
                "trade_authorized": False}
    except PublicReferenceRejected:
        raise
    except (ValueError, KeyError, TypeError, OverflowError):
        raise PublicReferenceRejected("public_reference_schema_invalid") from None
