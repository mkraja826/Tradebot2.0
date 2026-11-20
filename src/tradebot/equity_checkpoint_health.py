"""Read-only FIRE equity checkpoint health, without AI or broker mutations.

A checkpoint is valid ONLY when an immutable, signed-wallet observation
occurred in the first five minutes after the UTC daily/weekly open. Missing
historical checkpoints must never be fabricated or backfilled from current
balances. This is a diagnostic, not an authorization to trade.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from tradebot.portfolio_equity_guard import ANCHOR_WINDOW, amount, stamp


def checkpoint_health(path, *, at=None, stale_after_seconds=180):
    """Return sanitized health and distinct pending-vs-missed alerts.

    Uses SQLite URI mode=ro; never creates, modifies, or migrates a ledger.
    """
    now = at if at is not None else datetime.now(timezone.utc)
    now_us = stamp(now)  # validates tz-aware datetime
    if type(stale_after_seconds) is not int or stale_after_seconds <= 0:
        raise ValueError("Invalid checkpoint freshness window")
    today = now.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week = today - timedelta(days=today.weekday())
    report = {
        "source": "delta_demo_signed_wallet",
        "timezone": "UTC",
        "mode": "read_only",
        "as_of": now.astimezone(timezone.utc).isoformat(),
        "daily_checkpoint": "unavailable",
        "weekly_checkpoint": "unavailable",
        "daily_window_end_utc": (
            today + timedelta(seconds=ANCHOR_WINDOW)
        ).isoformat(),
        "weekly_window_end_utc": (
            week + timedelta(seconds=ANCHOR_WINDOW)
        ).isoformat(),
        "latest_observation_age_seconds": None,
        "status": "evidence_unavailable",
        "checkpoint_prerequisites_met": False,
        "trade_authorized": False,
        "blocking_conditions": [],
        "alert_codes": [],
    }
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        report["blocking_conditions"].append("equity_ledger_unavailable")
        report["alert_codes"].append("equity_ledger_unavailable")
        return report

    try:
        with closing(sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5
        )) as db:
            db.execute("PRAGMA query_only=ON")
            latest = db.execute(
                "SELECT observed_us,equity_usd FROM equity_evidence "
                "ORDER BY observed_us DESC LIMIT 1"
            ).fetchone()

            def state(period_start):
                start = stamp(period_start)
                end = start + ANCHOR_WINDOW*1_000_000
                observation = db.execute(
                    "SELECT equity_usd FROM equity_evidence "
                    "WHERE observed_us>=? AND observed_us<=? AND observed_us<=? "
                    "ORDER BY observed_us LIMIT 1",
                    (start, end, now_us),
                ).fetchone()
                if observation:
                    amount(observation[0])
                    return "verified"
                return "pending_window" if now_us <= end else "missed_window"

            report["daily_checkpoint"] = state(today)
            report["weekly_checkpoint"] = state(week)
            if latest:
                observed_us, observed_equity = latest
                amount(observed_equity)
                if type(observed_us) is not int or observed_us > now_us:
                    raise ValueError("Future signed observation")
                report["latest_observation_age_seconds"] = int(
                    (now_us - observed_us) / 1_000_000
                )
    except (sqlite3.Error, ValueError, TypeError, OSError):
        report["daily_checkpoint"] = "unavailable"
        report["weekly_checkpoint"] = "unavailable"
        report["latest_observation_age_seconds"] = None
        report["blocking_conditions"].append("equity_ledger_unavailable")
        report["alert_codes"].append("equity_ledger_unavailable")
        return report

    for name in ("daily", "weekly"):
        status = report[name + "_checkpoint"]
        if status != "verified":
            report["blocking_conditions"].append(name + "_checkpoint_" + status)
            if status == "missed_window":
                report["alert_codes"].append("missed_" + name + "_checkpoint")
    age = report["latest_observation_age_seconds"]
    if age is None or age > stale_after_seconds:
        report["blocking_conditions"].append("signed_equity_observation_stale")
        report["alert_codes"].append("signed_equity_observation_stale")

    report["checkpoint_prerequisites_met"] = not report["blocking_conditions"]
    if any(s.endswith("missed_window") for s in report["blocking_conditions"]):
        report["status"] = "checkpoint_missed"
    elif report["alert_codes"]:
        report["status"] = "evidence_stale"
    elif report["blocking_conditions"]:
        report["status"] = "checkpoint_pending"
    else:
        report["status"] = "healthy"
    return report
