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
import json
import stat

from tradebot.equity_receipt import EquityReadError, validate_receipt

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


def validated_watermark(db):
    """Check the stored peak against all immutable history in this transaction.

    Equity is decimal text: SQL text ordering and binary floats can both hide
    a lowered peak. An inconsistency is evidence failure, never permission to
    repair the watermark or derive a replacement from the current wallet.
    """
    row = db.execute("SELECT high_usd FROM equity_watermark WHERE singleton=1").fetchone()
    if row is None:
        raise EquityRiskError("equity_watermark_missing")
    peak = amount(row[0])
    seen = False
    for equity, origin in db.execute("SELECT equity_usd,origin FROM equity_evidence"):
        seen = True
        if origin != "delta_demo_signed_wallet" or amount(equity) > peak:
            raise EquityRiskError("equity_watermark_inconsistent")
    if not seen:
        raise EquityRiskError("equity_history_or_watermark_missing")
    return peak


def require_receipt_backed_history(db, instant):
    """Fail closed before trade admission using one locked ledger snapshot.

    Historical opening and latest observations must carry their original
    authenticated-HTTPS transport receipts. This is not broker-signed proof.
    Missing first-of-period observations may be supplied by the *incoming*
    verified read only within their real UTC opening window. Existing
    receiptless opening records can never be silently superseded.
    """
    current_us = stamp(instant)
    utc = instant.astimezone(timezone.utc)
    today = utc.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    latest = db.execute(
        "SELECT observed_us,equity_usd FROM equity_evidence "
        "ORDER BY observed_us DESC LIMIT 1").fetchone()
    checked = set()

    def validate_historical(row):
        observed_us, equity = row
        if type(observed_us) is not int or observed_us <= 0:
            raise EquityRiskError("equity_checkpoint_receipt_unverified")
        if observed_us in checked:
            return
        saved = db.execute(
            "SELECT receipt FROM equity_read_receipts WHERE observed_us=?",
            (observed_us,)).fetchone()
        if saved is None or type(saved[0]) is not str:
            raise EquityRiskError("equity_checkpoint_receipt_missing")
        try:
            receipt = json.loads(saved[0])
            if (not isinstance(receipt, dict) or
                    type(receipt.get("received_us")) is not int or
                    receipt["received_us"] != observed_us):
                raise EquityRiskError("equity_checkpoint_receipt_unverified")
            origin = datetime.fromtimestamp(observed_us / 1_000_000, timezone.utc)
            verified = validate_receipt(equity, receipt, now=origin)
            if stamp(verified) != observed_us:
                raise EquityRiskError("equity_checkpoint_receipt_unverified")
        except (ValueError, TypeError, OverflowError) as exc:
            if isinstance(exc, EquityRiskError):
                raise
            raise EquityRiskError("equity_checkpoint_receipt_unverified") from None
        checked.add(observed_us)

    for period in (today, week):
        period_us = stamp(period)
        row = db.execute(
            "SELECT observed_us,equity_usd FROM equity_evidence "
            "WHERE observed_us>=? AND observed_us<=? AND observed_us<=? "
            "ORDER BY observed_us LIMIT 1",
            (period_us, period_us + ANCHOR_WINDOW * 1_000_000, current_us)
        ).fetchone()
        if row is not None:
            validate_historical(row)
        elif not period_us <= current_us <= period_us + ANCHOR_WINDOW * 1_000_000:
            raise EquityRiskError("missing_opening_equity_checkpoint")
    if latest is not None:
        if type(latest[0]) is not int or latest[0] > current_us:
            raise EquityRiskError("equity_observation_out_of_order_or_clock_reversed")
        validate_historical(latest)


class PortfolioEquityGuard:
    """One persistent loss budget shared by BTC and gold FIRE controllers."""

    def __init__(self, path, *, max_daily=Decimal("0.02"),
                 max_weekly=Decimal("0.05"), max_drawdown=Decimal("0.08"),
                 require_existing=False):
        self.path = Path(path)
        self.require_existing = require_existing
        self._identity = None
        if not require_existing:
            # Initialization is for isolated fixtures / separately approved
            # first-time provisioning, never automatic runtime recovery.
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise EquityRiskError("Refusing symlinked risk ledger")
        try:
            fd = os.open(self.path, os.O_RDWR | (0 if require_existing else os.O_CREAT) |
                         getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), 0o600)
        except FileNotFoundError:
            raise EquityRiskError("equity_ledger_unavailable") from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise EquityRiskError("equity_ledger_unavailable")
            if require_existing:
                self._identity = (info.st_dev, info.st_ino)
        finally:
            os.close(fd)
        os.chmod(self.path, 0o600)
        self.limits = tuple(amount(x) for x in (max_daily, max_weekly, max_drawdown))
        if any(x >= 1 for x in self.limits):
            raise EquityRiskError("Invalid loss-limit fractions")
        with closing(self._connect()) as db:
            if require_existing:
                # Do this before migrations or WAL changes. An empty file or
                # missing schema is missing history, not a fresh risk baseline.
                db.execute("BEGIN")
                if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                    raise EquityRiskError("equity_database_integrity_failed")
                latest = db.execute("SELECT equity_usd,origin FROM equity_evidence "
                                    "ORDER BY observed_us DESC LIMIT 1").fetchone()
                peak = db.execute("SELECT high_usd FROM equity_watermark WHERE singleton=1").fetchone()
                if latest is None or peak is None:
                    raise EquityRiskError("equity_history_or_watermark_missing")
                validated_watermark(db)
                db.commit()
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS equity_evidence(
                    observed_us INTEGER PRIMARY KEY,
                    equity_usd TEXT NOT NULL,
                    origin TEXT NOT NULL CHECK(origin='delta_demo_signed_wallet'));
                CREATE TABLE IF NOT EXISTS equity_watermark(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    high_usd TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS equity_read_receipts(
                    observed_us INTEGER PRIMARY KEY REFERENCES equity_evidence(observed_us),
                    receipt TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS reject_equity_evidence_update
                    BEFORE UPDATE ON equity_evidence BEGIN
                    SELECT RAISE(ABORT, 'Immutable equity observation');
                END;
                CREATE TRIGGER IF NOT EXISTS reject_equity_evidence_replace
                    BEFORE INSERT ON equity_evidence
                    WHEN EXISTS(SELECT 1 FROM equity_evidence WHERE observed_us=NEW.observed_us)
                    BEGIN SELECT RAISE(ABORT, 'Immutable equity observation'); END;
                CREATE TRIGGER IF NOT EXISTS reject_equity_receipt_replace
                    BEFORE INSERT ON equity_read_receipts
                    WHEN EXISTS(SELECT 1 FROM equity_read_receipts WHERE observed_us=NEW.observed_us)
                    BEGIN SELECT RAISE(ABORT, 'Immutable equity receipt'); END;
                CREATE TRIGGER IF NOT EXISTS reject_equity_receipt_update
                    BEFORE UPDATE ON equity_read_receipts BEGIN
                    SELECT RAISE(ABORT, 'Immutable equity receipt');
                END;
                CREATE TRIGGER IF NOT EXISTS reject_equity_receipt_delete
                    BEFORE DELETE ON equity_read_receipts BEGIN
                    SELECT RAISE(ABORT, 'Immutable equity receipt');
                END;
                CREATE TRIGGER IF NOT EXISTS reject_equity_evidence_delete
                    BEFORE DELETE ON equity_evidence BEGIN
                    SELECT RAISE(ABORT, 'Immutable equity observation');
                END;
            """)
        self._check_identity()

    def _check_identity(self):
        if not self.require_existing:
            return
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            raise EquityRiskError("equity_ledger_unavailable") from None
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != self._identity:
            raise EquityRiskError("equity_ledger_replaced")

    def _connect(self):
        self._check_identity()
        if not self.require_existing:
            return sqlite3.connect(self.path, timeout=20)
        # mode=rw, unlike the SQLite default, cannot recreate a missing ledger
        # if it vanishes between checks or later in this process's lifetime.
        db = sqlite3.connect(self.path.absolute().as_uri() + "?mode=rw", uri=True, timeout=20)
        try:
            self._check_identity()
        except Exception:
            db.close()
            raise
        return db

    def latest_observed_us(self):
        with closing(self._connect()) as db:
            record = db.execute("SELECT max(observed_us) FROM equity_evidence").fetchone()
        return record[0]

    @staticmethod
    def _opening(db, period_start_us, instant_us):
        rows = db.execute(
            "SELECT equity_usd,origin FROM equity_evidence WHERE observed_us>=? "
            "AND observed_us<=? AND observed_us<=? ORDER BY observed_us LIMIT 1",
            (period_start_us, period_start_us + ANCHOR_WINDOW*1000000, instant_us)
        ).fetchone()
        if rows and rows[1] != "delta_demo_signed_wallet":
            raise EquityRiskError("Unverified opening equity origin")
        return amount(rows[0]) if rows else None

    def observe(self, equity, *, at=None, receipt=None, enforce_receipt_history=False):
        """Persist exactly one signed-wallet derived equity reading.

        Internal persistence helper, also used by offline fixtures. Runtime
        callers MUST use observe_verified_read / observe_signed_demo. There is
        deliberately no CLI for importing or backdating opening observations.
        """
        instant = at or datetime.now(timezone.utc)
        current_us = stamp(instant)
        current = amount(equity)
        day_start = instant.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise EquityRiskError("equity_database_integrity_failed")
            latest = db.execute("SELECT max(observed_us) FROM equity_evidence").fetchone()[0]
            if self.require_existing and latest is None:
                raise EquityRiskError("equity_history_or_watermark_missing")
            if latest is not None and current_us < latest:
                raise EquityRiskError("equity_observation_out_of_order_or_clock_reversed")
            peak_row = db.execute(
                "SELECT high_usd FROM equity_watermark WHERE singleton=1").fetchone()
            if latest is not None and peak_row is None:
                raise EquityRiskError("equity_watermark_missing")
            if latest is not None:
                validated_watermark(db)
            if enforce_receipt_history:
                if receipt is None:
                    raise EquityRiskError("equity_read_receipt_missing")
                require_receipt_backed_history(db, instant)
            old = db.execute("SELECT equity_usd FROM equity_evidence WHERE observed_us=?",
                             (current_us,)).fetchone()
            if old is not None:
                if amount(old[0]) != current:
                    raise EquityRiskError("Conflicting signed equity evidence timestamp")
            else:
                db.execute("INSERT INTO equity_evidence VALUES (?,?,'delta_demo_signed_wallet')",
                           (current_us, str(current)))
            if receipt is not None:
                encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
                existing = db.execute("SELECT receipt FROM equity_read_receipts WHERE observed_us=?",
                                      (current_us,)).fetchone()
                if existing is not None and existing[0] != encoded:
                    raise EquityRiskError("Conflicting signed equity receipt timestamp")
                if old is not None and existing is None:
                    raise EquityRiskError("Cannot retroactively attest historical equity")
                if existing is None:
                    db.execute("INSERT INTO equity_read_receipts VALUES (?,?)", (current_us, encoded))
            peak = max(current, amount(peak_row[0])) if peak_row else current
            db.execute(
                "INSERT INTO equity_watermark(singleton,high_usd) VALUES (1,?) "
                "ON CONFLICT(singleton) DO UPDATE SET high_usd=excluded.high_usd",
                (str(peak),))
            daily = self._opening(db, stamp(day_start), current_us)
            weekly = self._opening(db, stamp(week_start), current_us)
            db.commit()
        self._check_identity()

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

    def observe_verified_read(self, equity, receipt, *, now=None):
        instant = validate_receipt(equity, receipt, now=now)
        return self.observe(equity, at=instant, receipt=receipt)

    def require_verified_read(self, equity, receipt, *, now=None):
        # Admission checks historical receipts under the same write lock as
        # the fresh observation. The collector uses observe_verified_read and
        # can still record diagnostics when legacy history is incomplete.
        instant = validate_receipt(equity, receipt, now=now)
        report = self.observe(equity, at=instant, receipt=receipt,
                              enforce_receipt_history=True)
        if not report["approved"]:
            raise EquityRiskError(report["reason"])
        return report

    def observe_signed_demo(self, exchange):
        """Only signed DEMO wallet reads may populate the risk history."""
        from tradebot.delta import DEMO_API
        if getattr(exchange, "base_url", None) != DEMO_API:
            raise EquityRiskError("Non-demo equity source refused")
        balances = exchange.wallet_balances()
        return self.observe_verified_read(balances["meta"]["net_equity"],
                                          balances.get("equity_read_receipt"))

    def require_approved(self, equity, *, receipt=None, now=None, at=None):
        """Legacy name cannot approve a bare, caller-asserted equity amount."""
        if at is not None or receipt is None:
            raise EquityRiskError("verified_equity_receipt_required")
        return self.require_verified_read(equity, receipt, now=now)


class RuntimeEquityGuard:
    """Lazy existing-only access: diagnostic startup must survive risk DB faults.

    There is no initializer, repair, reset or backfill path in this facade.
    Opening or replacing evidence is an explicit operator recovery concern.
    """

    def __init__(self, path):
        self.path = Path(path)
        self._guard = None

    def _existing(self):
        if self._guard is None:
            self._guard = PortfolioEquityGuard(self.path, require_existing=True)
        return self._guard

    def require_verified_read(self, equity, receipt, *, now=None):
        return self._existing().require_verified_read(equity, receipt, now=now)

    def observe_signed_demo(self, exchange):
        return self._existing().observe_signed_demo(exchange)
