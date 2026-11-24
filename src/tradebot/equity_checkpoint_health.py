"""Read-only FIRE equity checkpoint health, without AI or broker mutations.

A checkpoint is valid ONLY when an immutable, signed-wallet observation
occurred strictly before 00:05:00 UTC, in the half-open first five-minute window. Missing
historical checkpoints must never be fabricated or backfilled from current
balances. This is a diagnostic, not an authorization to trade.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from tradebot.equity_policy_core import ANCHOR_WINDOW, amount, stamp, validated_watermark
from tradebot.equity_receipt import EquityReadError, validate_receipt


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
        "latest_observation_utc": None,
        "observation_status": "unavailable",
        "latest_receipt_status": "unavailable",
        "database_integrity": "unavailable",
        "daily_next_window_start_utc": (today + timedelta(days=1)).isoformat(),
        "weekly_next_window_start_utc": (week + timedelta(days=7)).isoformat(),
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
            db.execute("BEGIN")  # one consistent view despite concurrent collectors
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise ValueError("Database integrity failure")
            # An uncommissioned legacy ledger may legitimately predate the
            # immutable transport receipt table. Its rows are NOT corrupt,
            # and neither a read-only health probe nor the diagnostics CLI
            # may silently migrate it. Report an explicit fail-closed schema
            # prerequisite rather than a misleading SQLite integrity fault.
            has_receipts = db.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='equity_read_receipts'"
            ).fetchone() is not None
            if not has_receipts:
                report["database_integrity"] = "verified"
                report["status"] = "legacy_receipt_schema_uncommissioned"
                report["blocking_conditions"].append("equity_receipt_schema_missing")
                report["alert_codes"].append("equity_read_receipt_invalid")
                return report
            latest = db.execute(
                "SELECT observed_us,equity_usd,origin FROM equity_evidence "
                "ORDER BY observed_us DESC LIMIT 1"
            ).fetchone()

            def receipt_status(observed_us, observed_equity):
                """Inspect saved historical transport evidence at its own clock time.

                Never refresh/backdate stored provenance with the current clock.
                Legacy rows lacking a receipt remain unverified, even when the
                signed-wallet origin label is present. No database writes.
                """
                if type(observed_us) is not int or observed_us <= 0:
                    return "invalid"
                raw = db.execute(
                    "SELECT receipt FROM equity_read_receipts WHERE observed_us=?",
                    (observed_us,),
                ).fetchone()
                if raw is None:
                    return "missing"
                try:
                    saved = json.loads(raw[0])
                    if (not isinstance(saved, dict) or
                            type(saved.get("received_us")) is not int or
                            saved["received_us"] != observed_us):
                        return "invalid"
                    at = datetime.fromtimestamp(observed_us / 1_000_000, timezone.utc)
                    verified_at = validate_receipt(observed_equity, saved, now=at)
                    return "verified" if stamp(verified_at) == observed_us else "invalid"
                except (EquityReadError, ValueError, TypeError, OverflowError):
                    return "invalid"

            def state(period_start):
                start = stamp(period_start)
                end = start + ANCHOR_WINDOW*1_000_000
                observation = db.execute(
                    "SELECT observed_us,equity_usd,origin FROM equity_evidence "
                    "WHERE observed_us>=? AND observed_us<? AND observed_us<=? "
                    "ORDER BY observed_us LIMIT 1",
                    (start, end, now_us),
                ).fetchone()
                if observation:
                    amount(observation[1])
                    if observation[2] != "delta_demo_signed_wallet":
                        raise ValueError("Unverified observation origin")
                    return ("verified" if receipt_status(observation[0], observation[1]) == "verified"
                            else "unverified_receipt")
                return "pending_window" if now_us < end else "missed_window"

            report["daily_checkpoint"] = state(today)
            report["weekly_checkpoint"] = state(week)
            if latest:
                observed_us, observed_equity, origin = latest
                amount(observed_equity)
                if type(observed_us) is not int or origin != "delta_demo_signed_wallet":
                    raise ValueError("Invalid signed observation")
                if observed_us > now_us:
                    report["alert_codes"].append("equity_clock_inconsistent")
                    raise ValueError("Future observation; clock or evidence invalid")
                validated_watermark(db)
                report["latest_receipt_status"] = receipt_status(observed_us, observed_equity)
                report["latest_observation_age_seconds"] = (now_us - observed_us) / 1_000_000
                report["latest_observation_utc"] = datetime.fromtimestamp(
                    observed_us / 1_000_000, timezone.utc).isoformat()
            report["database_integrity"] = "verified"
    except (sqlite3.Error, ValueError, TypeError, OSError):
        report["daily_checkpoint"] = "unavailable"
        report["weekly_checkpoint"] = "unavailable"
        report["latest_observation_age_seconds"] = None
        report["latest_observation_utc"] = None
        report["latest_receipt_status"] = "unavailable"
        report["database_integrity"] = "failed"
        report["blocking_conditions"].append("equity_ledger_unavailable")
        report["blocking_conditions"].extend(report["alert_codes"])
        report["alert_codes"].append("equity_ledger_integrity_failed")
        return report

    for name in ("daily", "weekly"):
        status = report[name + "_checkpoint"]
        if status != "verified":
            report["blocking_conditions"].append(name + "_checkpoint_" + status)
            if status == "missed_window":
                report["alert_codes"].append("missed_" + name + "_checkpoint")
            elif status == "unverified_receipt":
                report["alert_codes"].append("equity_read_receipt_invalid")
    age = report["latest_observation_age_seconds"]
    report["observation_status"] = ("unverified_receipt"
                                    if report["latest_receipt_status"] in ("missing", "invalid")
                                    else "stale" if age is None or age > stale_after_seconds
                                    else "fresh")
    if report["latest_receipt_status"] in ("missing", "invalid"):
        report["blocking_conditions"].append("latest_equity_read_receipt_unverified")
        report["alert_codes"].append("equity_read_receipt_invalid")
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
