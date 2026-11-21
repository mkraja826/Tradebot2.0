"""Synthetic receipt fixtures. Never used by deployed code or against a broker."""
from datetime import datetime, timezone
import hashlib

from tradebot.equity_receipt import SOURCE


def receipt_for(equity="1000", at=None):
    now = at or datetime.now(timezone.utc)
    received = int(now.timestamp() * 1_000_000)
    return {
        "source": SOURCE, "equity_usd": equity,
        "request_started_us": received, "received_us": received,
        "server_date_us": received // 1_000_000 * 1_000_000,
        "elapsed_us": 0, "cache_age_seconds": 0,
        "response_sha256": hashlib.sha256(str(equity).encode()).hexdigest(),
    }
