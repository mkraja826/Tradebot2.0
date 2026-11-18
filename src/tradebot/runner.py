"""Clock-driven orchestration for the BTC demo AI agent.

"observe" is strictly read-only. "demo" requires two explicit opt-ins and a
demo-only exchange client, and MUST be run in a supervised, verified testnet.
A model is never trusted to decide when the end-of-session rule applies.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from uuid import uuid4
import fcntl
import os
import sys
import signal
from threading import Event

from tradebot.decision import build_ai_context
from tradebot.delta import DEMO_API
from tradebot.execution import CloseoutError, DemoExecutor
from tradebot.journal import record, recent
from tradebot.market import collect_market_snapshot
from tradebot.preflight import check_entry, PreflightError
from tradebot.session import SessionPhase, session_phase


class RunnerError(RuntimeError):
    pass


class ExposureAlert(RunnerError):
    pass


@dataclass(frozen=True)
class RunnerConfig:
    mode: str = "observe"
    ai_interval_seconds: int = 300
    poll_seconds: int = 15
    max_options: int = 128
    journal_path: str = "data/trades.jsonl"

    def __post_init__(self):
        if self.mode not in ("observe", "demo"):
            raise ValueError("mode must be observe or demo")
        if not 30 <= self.ai_interval_seconds <= 3600:
            raise ValueError("ai_interval_seconds must be 30..3600")
        if not 2 <= self.poll_seconds <= 60:
            raise ValueError("poll_seconds must be 2..60")
        if not 8 <= self.max_options <= 512:
            raise ValueError("max_options must be 8..512")


class SingleInstance:
    """Exclusive advisory file lock, intended for Linux / single host."""

    def __init__(self, path: str):
        self.path = path
        self._handle = None

    def __enter__(self):
        lock_path = Path(self.path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise RunnerError("A bot process already owns this demo account lock") from exc
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(str(os.getpid()) + "\n")
        self._handle.flush()
        return self

    def __exit__(self, *_):
        if self._handle:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


class BotRunner:
    def __init__(self, exchange, planner, *, config=None, now=None,
                 pause=None, snapshot_fn=None, executor=None):
        self.exchange = exchange
        self.planner = planner
        self.config = config or RunnerConfig()
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.pause = pause or sleep
        self.snapshot_fn = snapshot_fn or collect_market_snapshot
        self.executor = executor or DemoExecutor(
            exchange, journal_path=self.config.journal_path, now=self.now)
        self.last_ai_utc = None
        self.halted_session = None
        if self.config.mode == "demo":
            if getattr(exchange, "base_url", None) != DEMO_API:
                raise RunnerError("Demo mode forbids any non-testnet exchange host")
            if getattr(exchange, "allow_orders", False) is not True:
                raise RunnerError("Demo mode requires an explicitly enabled demo client")

    def _record(self, kind, details):
        record(self.config.journal_path, kind, details)

    def tick(self):
        instant = self.now()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise RunnerError("Timezone-aware clock required")
        instant = instant.astimezone(timezone.utc)
        phase = session_phase(instant)
        if phase != SessionPhase.TRADING:
            if self.config.mode == "demo":
                self.executor.closeout()
                self._record("session_flat", {"phase": phase.value})
            else:
                # Observe mode never mutates positions; flag any exposure.
                positions = self.exchange.btc_positions()
                active = self.exchange.open_orders()
                if positions or any(
                    str(o.get("product_symbol") or "").upper().startswith(
                        ("BTC", "C-BTC-", "P-BTC-")
                    ) for o in active
                ):
                    self._record("exposure_alert", {"phase": phase.value,
                        "message": "Read-only bot found exposure outside session"})
                    raise ExposureAlert("BTC exposure outside session; observe mode cannot close it")
            return {"phase": phase.value, "action": "closeout" if self.config.mode == "demo"
                    else "observed_flat"}

        # If any prior entry or exchange operation fails, no more entries in
        # this runner session. An operator must review/restart after resolution.
        if self.halted_session is not None:
            if self.config.mode == "demo":
                self.executor.closeout()
            return {"phase": phase.value, "action": "halted"}

        if self.last_ai_utc is not None and (
            instant - self.last_ai_utc
        ).total_seconds() < self.config.ai_interval_seconds:
            return {"phase": phase.value, "action": "cooldown"}

        # Read account state before invoking a costly AI call.
        open_orders = self.exchange.open_orders()
        if open_orders:
            # Includes non-BTC open orders: dedicated demo accounts only.
            self._record("observe_pending_orders", {"count": len(open_orders)})
            return {"phase": phase.value, "action": "pending_orders"}

        positions = self.exchange.btc_positions()
        snapshot = self.snapshot_fn(self.exchange, now=instant, include_balances=True)
        context, products = build_ai_context(
            snapshot, max_options=self.config.max_options)
        context["btc_positions"] = positions
        context["open_orders_count"] = 0
        self.last_ai_utc = instant
        plan = self.planner.propose(
            context, products, recent(self.config.journal_path))
        self._record("ai_decision", {
            "at": instant.isoformat(), "mode": self.config.mode,
            "strategy": plan.strategy, "rationale": plan.rationale,
            "legs": [{"product_id": leg.product_id, "side": leg.side,
                      "size": leg.size} for leg in plan.orders],
        })
        if self.config.mode == "observe":
            return {"phase": phase.value, "action": "preview",
                    "strategy": plan.strategy, "legs": len(plan.orders)}

        if not plan.orders:
            return {"phase": phase.value, "action": "wait", "strategy": plan.strategy}
        try:
            # Re-read quotes and demo funds AFTER AI reasoning. This is a
            # preflight sanity check, not a full option-spread margin model.
            check_entry(self.exchange, plan, products, now=self.now())
            # Requery exchange immediately before posting to avoid known
            # outstanding orders when decisions were being generated.
            if self.exchange.open_orders():
                raise PreflightError("Unexpected pending orders prior to entry")
            self.executor.execute(plan, products)
        except Exception as exc:
            self.halted_session = instant.date()
            self._record("execution_halt", {"error": type(exc).__name__,
                                             "phase": phase.value})
            # An unknown exchange result may have filled partially. Attempt
            # flatten now rather than waiting for the session cutoff.
            try:
                self.executor.closeout()
            except Exception as close_exc:
                self._record("exposure_alert", {
                    "error": type(close_exc).__name__,
                    "message": "BTC flatness unconfirmed following execution fault"})
                raise ExposureAlert(
                    "Demo order fault and unverified BTC closeout — intervene now"
                ) from close_exc
            raise RunnerError("Demo execution halted for this session") from exc
        return {"phase": phase.value, "action": "demo_order_submitted",
                "strategy": plan.strategy, "legs": len(plan.orders)}

    def run_forever(self, *, stop=None):
        """Keep retrying closeout on faults and flatten on graceful shutdown.

        stderr alerts are NOT sufficient as an unattended paging system.
        Independent process monitoring is required for host/power failures.
        """
        lock_path = self.config.journal_path + ".lock"
        requested_stop = Event()
        old_sigterm = None
        if stop is None:
            # Container/process supervisors typically send SIGTERM.
            try:
                old_sigterm = signal.getsignal(signal.SIGTERM)
                signal.signal(signal.SIGTERM, lambda *_: requested_stop.set())
            except ValueError:
                # Tests and embedded runners may execute in another thread.
                old_sigterm = None
        try:
            with SingleInstance(lock_path):
                try:
                    while not requested_stop.is_set() and (stop is None or not stop()):
                        try:
                            result = self.tick()
                            print(result, flush=True)
                        except KeyboardInterrupt:
                            raise
                        except Exception as exc:
                            print("TRADEBOT ALERT: " + type(exc).__name__ + ": " +
                                  str(exc), file=sys.stderr, flush=True)
                        self.pause(self.config.poll_seconds)
                finally:
                    if self.config.mode == "demo":
                        # Shutdown midway through a session must not abandon
                        # positions. Exchange downtime can still prevent exit.
                        try:
                            self.executor.closeout()
                        except Exception as exc:
                            self._record("shutdown_exposure_alert", {
                                "reason": type(exc).__name__})
                            print("TRADEBOT CRITICAL: Shutdown cannot confirm "
                                  "BTC positions are flat", file=sys.stderr, flush=True)
                            raise
        finally:
            if old_sigterm is not None:
                signal.signal(signal.SIGTERM, old_sigterm)
