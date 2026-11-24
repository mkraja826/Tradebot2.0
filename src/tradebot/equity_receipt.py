"""Transport provenance for authenticated wallet reads; never trade authority.

HTTP Date/Age and monotonic elapsed time detect clock jumps, delayed reads and
cached responses. They do NOT prove the broker's internal valuation timestamp
or constitute a cryptographic signature of the response. No secrets are stored.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re

SOURCE = "delta_demo_authenticated_https"
MAX_READ_AGE_SECONDS = 30
RECEIPT_FIELDS = {"source", "equity_usd", "request_started_us", "received_us",
                  "server_date_us", "elapsed_us", "cache_age_seconds", "response_sha256"}


class EquityReadError(ValueError):
    """An allowlisted reason code, safe to publish without exception details."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_receipt(equity, receipt, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise EquityReadError("clock_unverified")
    if receipt == {"failure": "broker_time_evidence_unavailable"}:
        raise EquityReadError("broker_time_evidence_unavailable")
    if not isinstance(receipt, dict) or receipt.get("source") != SOURCE:
        raise EquityReadError("equity_read_receipt_missing")
    if set(receipt) != RECEIPT_FIELDS:
        raise EquityReadError("equity_read_receipt_invalid")
    for key in ("request_started_us", "received_us", "server_date_us", "elapsed_us"):
        if type(receipt.get(key)) is not int or receipt[key] < 0:
            raise EquityReadError("equity_read_receipt_invalid")
    if not isinstance(receipt.get("response_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", receipt["response_sha256"]
    ):
        raise EquityReadError("equity_read_receipt_invalid")
    try:
        value, attested = Decimal(str(equity)), Decimal(str(receipt["equity_usd"]))
        if not value.is_finite() or value <= 0 or value != attested:
            raise EquityReadError("equity_read_value_mismatch")
    except (KeyError, InvalidOperation):
        raise EquityReadError("equity_read_value_mismatch") from None
    started, received, server, elapsed = (
        receipt[k] for k in ("request_started_us", "received_us", "server_date_us", "elapsed_us")
    )
    if received < started or abs(received - started - elapsed) > 1_000_000:
        raise EquityReadError("system_clock_jump")
    if elapsed > 10_000_000:
        raise EquityReadError("broker_equity_read_slow")
    # Date has one-second resolution. Absence or an offset is uncertainty,
    # never grounds for silently adjusting the local clock or observation time.
    if not started - 5_000_000 <= server <= received + 5_000_000:
        raise EquityReadError("broker_clock_or_stale_response")
    if type(receipt.get("cache_age_seconds")) is not int or receipt["cache_age_seconds"] != 0:
        raise EquityReadError("broker_equity_response_cached")
    now_us = int(now.timestamp() * 1_000_000)
    if received > now_us:
        raise EquityReadError("system_clock_jump")
    if now_us - received > MAX_READ_AGE_SECONDS * 1_000_000:
        raise EquityReadError("broker_equity_read_stale")
    # A response straddling midnight cannot establish which period's opening
    # was observed. Wait for the next genuine read, never move its timestamp.
    day = 86_400_000_000
    if (started // day != received // day or server // day != received // day
            or now_us // day != received // day):
        raise EquityReadError("equity_boundary_ambiguous")
    return datetime.fromtimestamp(received / 1_000_000, timezone.utc)
