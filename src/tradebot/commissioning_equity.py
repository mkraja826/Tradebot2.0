"""Evaluate fresh signed wallet equity against existing anchors without writes."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import stat

from tradebot.delta import DEMO_API
from tradebot.equity_monitor import risk_health
from tradebot.equity_receipt import validate_receipt, EquityReadError
from tradebot.equity_policy_core import (
    DEFAULT_LIMITS, PortfolioEquityGuard, EquityRiskError, amount, assess_equity, stamp,
    validated_watermark,
)


def _ledger_identity(path):
    """Never permit a different or symlinked ledger during one readiness review."""
    try:
        details = path.lstat()
    except OSError:
        raise EquityRiskError("equity_ledger_unavailable") from None
    if not stat.S_ISREG(details.st_mode):
        raise EquityRiskError("equity_ledger_replaced")
    return details.st_dev, details.st_ino


def _verified_local_receipt(db, observed_us, equity_usd):
    """Validate historical transport provenance without falsely refreshing it.

    All local opening/most-recent samples used for commissioning must carry a
    receipt written at observation time, not just an unverifiable origin label.
    The original receipt is validated against its own observed timestamp, not
    the current clock. This is an authenticated-HTTPS transport attestation,
    not a cryptographic exchange signature or verified valuation timestamp.
    """
    if type(observed_us) is not int or observed_us <= 0:
        raise EquityRiskError("equity_checkpoint_receipt_unverified")
    row = db.execute("SELECT receipt FROM equity_read_receipts WHERE observed_us=?",
                     (observed_us,)).fetchone()
    if row is None or type(row[0]) is not str:
        raise EquityRiskError("equity_checkpoint_receipt_missing")
    try:
        receipt = json.loads(row[0])
        if (not isinstance(receipt, dict) or
                receipt.get("received_us") != observed_us):
            raise EquityRiskError("equity_checkpoint_receipt_unverified")
        observed_at = datetime.fromtimestamp(observed_us / 1_000_000, timezone.utc)
        verified_at = validate_receipt(equity_usd, receipt, now=observed_at)
        if stamp(verified_at) != observed_us:
            raise EquityRiskError("equity_checkpoint_receipt_unverified")
    except (ValueError, TypeError, OverflowError, EquityReadError) as exc:
        if isinstance(exc, EquityRiskError):
            raise
        raise EquityRiskError("equity_checkpoint_receipt_unverified") from None


def _require_signed_anchor_receipts(db, day_start, week_start, cutoff_us):
    """Check opening and latest observations from one read-only SQLite view."""
    checked = set()
    for start in (day_start, week_start):
        start_us = stamp(start)
        row = db.execute(
            "SELECT observed_us,equity_usd FROM equity_evidence "
            "WHERE observed_us>=? AND observed_us<? AND observed_us<=? "
            "ORDER BY observed_us LIMIT 1",
            (start_us, start_us + 300_000_000, cutoff_us)
        ).fetchone()
        if row is None:
            raise EquityRiskError("equity_opening_checkpoint_missing")
        if row[0] not in checked:
            _verified_local_receipt(db, row[0], row[1])
            checked.add(row[0])
    latest = db.execute(
        "SELECT observed_us,equity_usd FROM equity_evidence "
        "ORDER BY observed_us DESC LIMIT 1").fetchone()
    if latest is None or latest[0] > cutoff_us:
        raise EquityRiskError("equity_latest_observation_unverified")
    if latest[0] not in checked:
        _verified_local_receipt(db, latest[0], latest[1])


def signed_equity_readiness(exchange, data_dir, *, now=None):
    if getattr(exchange, "base_url", None) != DEMO_API or getattr(exchange, "allow_orders", None) is not False:
        raise EquityRiskError("Read-only DEMO client required")
    at = now or datetime.now(timezone.utc)
    path = Path(data_dir) / "fire-equity-risk.sqlite"
    # Keep the original risk evidence pinned through both health checks,
    # the wallet network read, and the final read-only SQLite transaction.
    # The runtime collector has a similar existing-file identity guard.
    try:
        original_identity = _ledger_identity(path)
    except EquityRiskError:
        # Preserve the read-only diagnostic API's denial response for an
        # absent/invalid ledger, without creating or repairing evidence.
        health = risk_health(path, at=at)
        return {"approved": False, "reason": "equity_or_monitoring_prerequisites_missing",
                "health": health, "trade_authorized": False}

    def require_same_ledger():
        if _ledger_identity(path) != original_identity:
            raise EquityRiskError("equity_ledger_replaced")

    health = risk_health(path, at=at)
    require_same_ledger()
    if not health["checkpoint_prerequisites_met"]:
        return {"approved": False, "reason": "equity_or_monitoring_prerequisites_missing",
                "health": health, "trade_authorized": False}
    # A legacy/synthetic opening may have an origin label but no stored
    # authenticated wallet transport receipt. Deny before using broker quota.
    day_at = at.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    week_at = day_at - timedelta(days=day_at.weekday())
    with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro",
                                 uri=True, timeout=5)) as db:
        require_same_ledger()
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        _require_signed_anchor_receipts(db, day_at, week_at, stamp(at))
        db.commit()
    require_same_ledger()
    wallet = exchange.wallet_balances()
    require_same_ledger()
    at = now or datetime.now(timezone.utc)
    current = amount(wallet["meta"]["net_equity"])
    receipt = wallet.get("equity_read_receipt")
    instant = validate_receipt(current, receipt, now=at)
    # Recheck after the network operation: midnight or stale telemetry during
    # the request must not inherit an earlier healthy result.
    health = risk_health(path, at=at)
    require_same_ledger()
    if not health["checkpoint_prerequisites_met"]:
        return {"approved": False, "reason": "equity_or_monitoring_prerequisites_missing",
                "health": health, "trade_authorized": False}
    day = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    week = day - timedelta(days=day.weekday())
    with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        require_same_ledger()
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
            raise EquityRiskError("equity_database_integrity_failed")
        latest = db.execute("SELECT observed_us,equity_usd FROM equity_evidence "
                            "ORDER BY observed_us DESC LIMIT 1").fetchone()
        if latest is None or type(latest[0]) is not int or latest[0] > stamp(instant):
            raise EquityRiskError("equity_observation_out_of_order_or_clock_reversed")
        _require_signed_anchor_receipts(db, day, week, stamp(instant))
        daily = PortfolioEquityGuard._opening(db, stamp(day), stamp(instant))
        weekly = PortfolioEquityGuard._opening(db, stamp(week), stamp(instant))
        peak = validated_watermark(db)
        assessment = assess_equity(current, daily, weekly, max(current, peak), instant, DEFAULT_LIMITS)
    require_same_ledger()
    # This assessment is not committed and cannot create a missing opening.
    return {**assessment, "health": health, "read_receipt": receipt,
            "mode": "read_only", "trade_authorized": False, "evidence_persisted": False}
