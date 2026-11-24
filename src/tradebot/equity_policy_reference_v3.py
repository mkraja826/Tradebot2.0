"""Native V3 research reference values; no admission or execution authority.
These mirror the existing reference thresholds for comparison only.
No approved production policy or historical loss reset is represented here.
"""
from datetime import datetime, timezone
from decimal import Decimal
ANCHOR_WINDOW = 300
DEFAULT_LIMITS = (Decimal("0.02"), Decimal("0.05"), Decimal("0.08"))
def stamp(value):
    if (not isinstance(value, datetime) or value.tzinfo is None
            or value.utcoffset() is None):
        raise ValueError("Timezone-aware observation is required")
    return int(value.astimezone(timezone.utc).timestamp() * 1_000_000)
