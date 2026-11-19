"""Fail-closed Delta Demo equity-loss guard, independent of every LLM.

Loss is measured as signed-wallet equity decline, including unrealized P&L.
It is NOT a broker-reconciled realized-P&L statement: transfers and funding
remain to be normalized. Period opening checkpoints must actually exist.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import sqlite3

DAY = 86400
ANCHOR_WINDOW = 300  # a signed snapshot from the first 5m of a UTC period


class EquityRiskError(ValueError):
    pass


def amount(raw):
    try:
        v = Decimal(str(raw))
    except (ValueError, TypeError, InvalidOperation):
        raise EquityRiskError("Verified account equity missing or invalid") from None
    if not v.is_finite() or v <= 0:
        raise EquityRiskError("Verified account equity must be positive")
    return v


def stamp(value):
    if (not isinstance(value, datetime) or value.tzinfo is None
            or value.utcoffset() is None):
        raise EquityRiskError("Timezone-aware observation is required")
    return int(value.astimezone(timezone.utc).timestamp() * 1_000_000)


class PortfolioEquityGuard:
    """One persistent loss budget shared by BTC and gold FIRE controllers."""

    def __init__(self, path, *, max_daily=Decimal("0.02"),
                 max_weekly=Decimal("0.05"), max_drawdown=Decimal("0.08")):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise EquityRiskError("Refusing symlinked risk ledger")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        self.limits = tuple(amount(x) for x in (max_daily, max_weekly, max_drawdown))
        if any(x >= 1 for x in self.limits):
            raise EquityRiskError("Invalid loss-limit fractions")
        with closing(sqlite3.connect(self.path, timeout=20)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS equity_evidence(
                    observed_us INTEGER PRIMARY KEY,
                    equity_usd TEXT NOT NULL,
                    origin TEXT NOT NULL CHECK(origin='delta_demo_signed_wallet'));
                CREATE TABLE IF NOT EXISTS equity_watermark(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    high_usd TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS reject_equity_evidence_update
                    BEFORE UPDATE ON equity_evidence BEGIN
                    SELECT RAISE(ABORT, 'Immutable equity observation');
                END;
                CREATE TRIGGER IF NOT EXISTS reject_equity_evidence_delete
                    BEFORE DELETE ON equity_evidence BEGIN
                    SELECT RAISE(ABORT, 'Immutable equity observation');
                END;
            """)

    def latest_observed_us(self):
        with closing(sqlite3.connect(self.path, timeout=20)) as db:
            record = db.execute("SELECT max(observed_us) FROM equity_evidence").fetchone()
        return record[0]

    @staticmethod
    def _opening(db, period_start_us, instant_us):
        rows = db.execute(
            "SELECT equity_usd FROM equity_evidence WHERE observed_us>=? "
            "AND observed_us<=? AND observed_us<=? ORDER BY observed_us LIMIT 1",
            (period_start_us, period_start_us + ANCHOR_WINDOW*1000000, instant_us)
        ).fetchone()
        return amount(rows[0]) if rows else None

    def observe(self, equity, *, at=None):
        """Persist exactly one signed-wallet derived equity reading.

        This function accepts an equity scalar, not a wallet body; callers
        must use an authenticated Delta India Demo read before calling.
        """
        instant = at or datetime.now(timezone.utc)
        current_us = stamp(instant)
        current = amount(equity)
        day_start = instant.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        with closing(sqlite3.connect(self.path, timeout=20)) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT equity_usd FROM equity_evidence WHERE observed_us=?",
                             (current_us,)).fetchone()
            if old is not None:
                if amount(old[0]) != current:
                    raise EquityRiskError("Conflicting signed equity evidence timestamp")
            else:
                db.execute("INSERT INTO equity_evidence VALUES (?,?,'delta_demo_signed_wallet')",
                           (current_us, str(current)))
            peak_row = db.execute(
                "SELECT high_usd FROM equity_watermark WHERE singleton=1").fetchone()
            peak = max(current, amount(peak_row[0])) if peak_row else current
            db.execute(
                "INSERT INTO equity_watermark(singleton,high_usd) VALUES (1,?) "
                "ON CONFLICT(singleton) DO UPDATE SET high_usd=excluded.high_usd",
                (str(peak),))
            daily = self._opening(db, stamp(day_start), current_us)
            weekly = self._opening(db, stamp(week_start), current_us)
            db.commit()

        status = {
            "policy": "delta-demo-equity-loss-v1",
            "source": "delta_demo_signed_wallet",
            "period_timezone": "UTC",
            "as_of": instant.astimezone(timezone.utc).isoformat(),
            "equity_usd": str(current),
            "daily_open_equity_usd": str(daily) if daily is not None else None,
            "weekly_open_equity_usd": str(weekly) if weekly is not None else None,
            "observed_high_watermark_usd": str(peak),
            "high_watermark_scope": "since_observation_started",
            "is_reconciled_realized_pnl": False,
            "approved": False,
        }
        if daily is None or weekly is None:
            status["reason"] = "missing_opening_equity_checkpoint"
            return status
        losses = tuple(
            max(Decimal("0"), (reference-current)/reference)
            for reference in (daily, weekly, peak)
        )
        status.update({
            "daily_equity_decline": str(losses[0]),
            "weekly_equity_decline": str(losses[1]),
            "observed_peak_drawdown": str(losses[2]),
            "limits": {
                "daily": str(self.limits[0]), "weekly": str(self.limits[1]),
                "drawdown": str(self.limits[2])
            },
        })
        violations = [name for name, loss, bound in zip(
            ("daily", "weekly", "drawdown"), losses, self.limits)
            if loss >= bound]
        if violations:
            status["reason"] = "loss_limit_" + "_".join(violations)
        else:
            status["reason"] = "within_observed_equity_limits"
            status["approved"] = True
        return status

    def observe_signed_demo(self, exchange, *, at=None):
        """Only signed DEMO wallet reads may populate the risk history."""
        from tradebot.delta import DEMO_API
        if getattr(exchange, "base_url", None) != DEMO_API:
            raise EquityRiskError("Non-demo equity source refused")
        balances = exchange.wallet_balances()
        return self.observe(balances["meta"]["net_equity"], at=at)

    def require_approved(self, equity, *, at=None):
        report = self.observe(equity, at=at)
        if not report["approved"]:
            raise EquityRiskError(report["reason"])
        return report
