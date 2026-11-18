"""US cash session phases from the actual NYSE calendar (DST, holidays, early closes)."""
from datetime import datetime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

NEW_YORK = ZoneInfo("America/New_York")
NYSE = xcals.get_calendar("XNYS")
FLATTEN_LEAD = timedelta(minutes=15)


class SessionPhase(str, Enum):
    CLOSED = "closed"
    TRADING = "trading"
    FLATTEN = "flatten"


def session_phase(instant: datetime) -> SessionPhase:
    """Trading only during NYSE cash hours, flatten in final 15 minutes.

    IMPORTANT: CLOSED does not mean positions may be left overnight.
    The executor must continue flatten retries and raise alerts after close.
    """
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required")
    utc = instant.astimezone(timezone.utc)
    ny_date = utc.astimezone(NEW_YORK).date()
    if not NYSE.is_session(ny_date):
        return SessionPhase.CLOSED
    session_open = NYSE.session_open(ny_date).to_pydatetime()
    session_close = NYSE.session_close(ny_date).to_pydatetime()
    if session_open <= utc < session_close - FLATTEN_LEAD:
        return SessionPhase.TRADING
    if session_close - FLATTEN_LEAD <= utc < session_close:
        return SessionPhase.FLATTEN
    return SessionPhase.CLOSED



SUPPORTED_SCHEDULES = frozenset({"nyse", "crypto-24x7"})


def entry_phase(instant: datetime, *, schedule: str = "nyse") -> SessionPhase:
    """Return whether new BTC entries are permitted for the explicit schedule.

    Legacy NYSE behavior remains the default. The crypto-24x7 policy never
    enforces NYSE closure and instead depends on independent execution, market
    freshness and account-risk gates. The timestamp must still be aware.
    """
    if schedule not in SUPPORTED_SCHEDULES:
        raise ValueError("Unsupported trade entry schedule")
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Timezone-aware datetime is required")
    if schedule == "crypto-24x7":
        return SessionPhase.TRADING
    return session_phase(instant)
