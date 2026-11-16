"""US cash-session schedule with daylight saving handled by IANA timezones."""
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
OPEN = time(9, 30)
ENTRY_CUTOFF = time(15, 45)
CLOSE = time(16, 0)


class SessionPhase(str, Enum):
    CLOSED = "closed"
    TRADING = "trading"
    FLATTEN = "flatten"


def session_phase(instant: datetime) -> SessionPhase:
    """Input must be timezone-aware. End-of-day flatten begins at 15:45 NY."""
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required")
    ny = instant.astimezone(NEW_YORK)
    if ny.weekday() >= 5:
        return SessionPhase.CLOSED
    local = ny.time().replace(tzinfo=None)
    if OPEN <= local < ENTRY_CUTOFF:
        return SessionPhase.TRADING
    if ENTRY_CUTOFF <= local < CLOSE:
        return SessionPhase.FLATTEN
    return SessionPhase.CLOSED
