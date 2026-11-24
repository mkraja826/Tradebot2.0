"""Read-only 5-minute post-close cooldown for isolated DEMO FIRE accounts.

A trade is complete only after a terminal broker-verified flat FIRE receipt.
The timestamp is the watchdog's UTC flat-verification write, not an assumed
exchange fill time or the start of the trade. Incomplete/malformed records
fail closed. The separate workers must independently confirm flat exposure.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import sqlite3

COOLDOWN_SECONDS = 5 * 60


def post_close_cooldown(root, *, fire_filename, now, seconds=COOLDOWN_SECONDS):
    """Return (status, seconds_left): ready, cooling_down, or unavailable.

    A no-order attempt is not a completed trade. A previous verified completed
    trade still imposes its five-minute cooldown even if a no-order receipt
    happened later. Only private isolated SQLite ledgers are permitted.
    """
    root = Path(root)
    name = {"btc-isolated": "fire-ops.sqlite",
            "gold-isolated": "fire-xaut.sqlite"}.get(root.name)
    if (name is None or fire_filename != name
            or root.is_symlink() or not root.is_dir()
            or now.tzinfo is None or now.utcoffset() is None
            or type(seconds) is not int or seconds < 1):
        return "unavailable", None
    file = root / fire_filename
    if file.is_symlink() or not file.is_file():
        return "unavailable", None
    try:
        with closing(sqlite3.connect(
                file.absolute().as_uri() + "?mode=ro",
                timeout=3, uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                "SELECT updated_at,result FROM fire_requests "
                "WHERE status='flat_verified' "
                "ORDER BY updated_at DESC LIMIT 1").fetchone()
        if row is None:
            return "ready", 0
        verified = json.loads(row[1])
        if (type(verified) is not dict
                or verified.get("orders_submitted") is not True
                or not verified.get("broker_order_id")
                or verified.get("reason_code") in (
                    "emergency_flat_verified",
                    "execution_or_protection_unverified")):
            return "unavailable", None
        instant = datetime.fromisoformat(row[0])
        if instant.tzinfo is None or instant.utcoffset() is None:
            return "unavailable", None
        delta=(now - instant).total_seconds()
        if not math.isfinite(delta) or delta < 0:
            return "unavailable", None
        if delta < seconds:
            return "cooling_down", math.ceil(seconds - delta)
        return "ready", 0
    except (sqlite3.Error, OSError, TypeError, ValueError, OverflowError,
            json.JSONDecodeError):
        return "unavailable", None



def require_entry_cooldown(root, *, fire_filename, now=None):
    """Mandatory pre-model AND pre-order gate for isolated autonomous bots.

    Each autonomous controller invokes this from its signed account-flat
    preflight, which the execution engine rechecks immediately before the
    broker order-intent path. Prevents a direct controller start from
    bypassing the scheduler's five-minute post-close check.
    """
    checked = now if now is not None else datetime.now(timezone.utc)
    state, _ = post_close_cooldown(
        root, fire_filename=fire_filename, now=checked)
    if state == "ready":
        return
    if state == "cooling_down":
        raise ValueError("autonomous_post_trade_cooldown_active")
    raise ValueError("autonomous_trade_close_evidence_unavailable")
