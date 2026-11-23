"""BTC supervised DEMO equity admission guard for the existing FIRE engine.

Only for an explicitly reviewed one-attempt controller. This never replaces
the standard week-anchored RuntimeEquityGuard on the dashboard. It does not
mint an order permit: the broker, 24h data and attached bracket gates are
separate and mandatory.
"""
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal

from tradebot.btc_supervised_session import (
    ALLOWED_STANDARD_BLOCKERS, _read_original_high_watermark,
    assess_supervised_session, isolated_btc_signed_genesis_window,
)
from tradebot.equity_monitor import (
    risk_health, demo_monitoring_operational, DAILY_ONLY_WARNING,
    PORTFOLIO_LOSS_WARNING,
)
from tradebot.equity_receipt import validate_receipt
from tradebot.portfolio_equity_guard import EquityRiskError, amount


class SupervisedSessionEquityGuard:
    """Retain genuine first signed equity reading for three FIRE entry checks.

    No historical equity row is edited or backfilled. Loss thresholds are
    applied to current authenticated wallet equity and original peak; the
    session is valid for at most 15 minutes. A restart cannot resume this
    in-memory baseline; the separately required one-shot lock stays consumed.
    """

    def __init__(self, path, *, health_fn=risk_health,
                 peak_reader=_read_original_high_watermark,
                 allow_daily_loss_warning=False,
                 allow_portfolio_loss_warnings=False,
                 allow_initial_isolated_genesis=False):
        self.path = Path(path)
        self.health_fn = health_fn
        self.peak_reader = peak_reader
        self.allow_daily_loss_warning = allow_daily_loss_warning
        self.allow_portfolio_loss_warnings = allow_portfolio_loss_warnings
        self.allow_initial_isolated_genesis = allow_initial_isolated_genesis
        self._first = None
        self._first_receipt = None
        self._file_identity = None

    def require_verified_read(self, equity, receipt, *, now=None):
        instant = now or datetime.now(timezone.utc)
        if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
            raise EquityRiskError("supervised_session_clock_unverified")
        current = amount(equity)
        validate_receipt(current, receipt, now=instant)
        health = self.health_fn(self.path, at=instant)
        if not isinstance(health, dict):
            raise EquityRiskError("supervised_session_history_unverified")
        monitor = health.get("monitoring")
        conditions = health.get("blocking_conditions")
        provisional = (
            self.allow_initial_isolated_genesis
            and isolated_btc_signed_genesis_window(self.path, health, instant))
        if (health.get("database_integrity") != "verified"
                or not (health.get("daily_checkpoint") == "verified"
                        or provisional)
                or health.get("latest_receipt_status") != "verified"
                or health.get("observation_status") != "fresh"
                or type(conditions) is not list
                or any(type(v) is not str for v in conditions)
                or not set(conditions) <= (ALLOWED_STANDARD_BLOCKERS |
                    ({"daily_checkpoint_missed_window"} if provisional else set()) |
                    ({DAILY_ONLY_WARNING} if self.allow_daily_loss_warning else set()) |
                    ({PORTFOLIO_LOSS_WARNING} if self.allow_portfolio_loss_warnings
                     else set()))
                or not demo_monitoring_operational(
                    monitor, allow_daily_loss_warning=self.allow_daily_loss_warning,
                    allow_portfolio_loss_warnings=self.allow_portfolio_loss_warnings)):
            raise EquityRiskError("supervised_session_history_or_monitor_unverified")
        peak, identity = self.peak_reader(self.path)
        if self._file_identity is not None and identity != self._file_identity:
            raise EquityRiskError("supervised_session_original_ledger_replaced")
        if self._first is None:
            # Deliberately set only after verifying original history AND the
            # current signed, fresh wallet receipt.
            self._first = current
            self._first_receipt = receipt
            self._file_identity = identity
        verdict = assess_supervised_session(
            self._first, current, peak, self._first_receipt,
            receipt, now=instant,
            allow_loss_warnings=self.allow_portfolio_loss_warnings)
        if not verdict["within_session_limits"]:
            raise EquityRiskError(verdict["reason"])
        quality_warnings = sorted(set(verdict.get("quality_warnings", [])) |
            (set(conditions) & {
                DAILY_ONLY_WARNING, PORTFOLIO_LOSS_WARNING}) |
            ({"provisional_first_day_signed_genesis"} if provisional else set()))
        return {
            "policy": "btc-demo-supervised-session-v1",
            "approved": True,
            "reason": ("loss_thresholds_warning_only" if quality_warnings
                       else "within_authenticated_short_session_limits"),
            "quality_warnings": quality_warnings,
            "session_elapsed_seconds": verdict["session_elapsed_seconds"],
            "normal_weekly_checkpoint_overridden": False,
            "daily_checkpoint_verified": health.get("daily_checkpoint") == "verified",
            "provisional_first_day_signed_genesis": bool(provisional),
            "separate_live_broker_protection_required": True,
        }
