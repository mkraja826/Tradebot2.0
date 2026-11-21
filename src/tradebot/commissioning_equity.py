"""Evaluate fresh signed wallet equity against existing anchors without writes."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import stat

from tradebot.delta import DEMO_API
from tradebot.equity_monitor import risk_health
from tradebot.equity_receipt import validate_receipt
from tradebot.portfolio_equity_guard import (
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
        daily = PortfolioEquityGuard._opening(db, stamp(day), stamp(instant))
        weekly = PortfolioEquityGuard._opening(db, stamp(week), stamp(instant))
        peak = validated_watermark(db)
        assessment = assess_equity(current, daily, weekly, max(current, peak), instant, DEFAULT_LIMITS)
    require_same_ledger()
    # This assessment is not committed and cannot create a missing opening.
    return {**assessment, "health": health, "read_receipt": receipt,
            "mode": "read_only", "trade_authorized": False, "evidence_persisted": False}
