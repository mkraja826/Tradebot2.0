"""Clock-driven orchestration for the BTC demo AI agent.

"observe" is strictly read-only. "demo" requires two explicit opt-ins and a
demo-only exchange client, and MUST be run in a supervised, verified testnet.
A model is never trusted to decide when the end-of-session rule applies.
"""
from dataclasses import dataclass
import json
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
from tradebot.execution import CloseoutError, DemoExecutor, _position_size
from tradebot.journal import record, recent
from tradebot.market import collect_market_snapshot
from tradebot.preflight import check_entry, PreflightError
from tradebot.session import SessionPhase, entry_phase


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
    schedule: str = "nyse"
    max_hold_seconds: int = 900
    max_order_legs: int = 4
    max_contracts_per_leg: int = 1

    def __post_init__(self):
        if self.mode not in ("observe", "demo"):
            raise ValueError("mode must be observe or demo")
        if not 30 <= self.ai_interval_seconds <= 3600:
            raise ValueError("ai_interval_seconds must be 30..3600")
        if not 2 <= self.poll_seconds <= 60:
            raise ValueError("poll_seconds must be 2..60")
        if not 8 <= self.max_options <= 512:
            raise ValueError("max_options must be 8..512")
        if self.schedule not in ("nyse", "crypto-24x7"):
            raise ValueError("Schedule must be nyse or crypto-24x7")
        if not 60 <= self.max_hold_seconds <= 3600:
            raise ValueError("max_hold_seconds must be 60..3600")
        if not 1 <= self.max_order_legs <= 4:
            raise ValueError("max_order_legs must be 1..4")
        if not 1 <= self.max_contracts_per_leg <= 5:
            raise ValueError("max_contracts_per_leg must be 1..5")


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
            exchange, journal_path=self.config.journal_path, now=self.now,
            schedule=self.config.schedule)
        self.last_ai_utc = None
        self.halted_session = None
        self.active_since = None
        self.halt_file = Path(self.config.journal_path + ".crypto24x7-halt")
        if self.config.mode == "demo":
            if getattr(exchange, "base_url", None) != DEMO_API:
                raise RunnerError("Demo mode forbids any non-testnet exchange host")
            if getattr(exchange, "allow_orders", False) is not True:
                raise RunnerError("Demo mode requires an explicitly enabled demo client")

    def _record(self, kind, details):
        record(self.config.journal_path, kind, details)

    def _trip_halt(self, cause: str) -> None:
        """Persist entry suspension through VM restarts until human review."""
        if self.config.schedule != "crypto-24x7" or self.config.mode != "demo":
            return
        self.halt_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.halt_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600) if not self.halt_file.exists() else None
        if fd is not None:
            with os.fdopen(fd, "w") as out:
                out.write("24x7 demo execution halted: " + cause + "\n")
        self._record("crypto24x7_halt", {"reason": cause})

    def tick(self):
        instant = self.now()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise RunnerError("Timezone-aware clock required")
        instant = instant.astimezone(timezone.utc)
        phase = entry_phase(instant, schedule=self.config.schedule)
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

        if self.config.schedule == "crypto-24x7" and self.config.mode == "demo":
            # Emergency kill switch survives reboot and systemd restart.
            if self.halt_file.exists():
                self.executor.closeout()
                return {"phase": phase.value, "action": "halted_persistent"}
            # Check exposure EVERY poll, even while AI is in cooldown.
            # No stacking a new AI strategy on top of existing positions.
            orders = self.exchange.open_orders()
            if orders:
                self.halted_session = instant.date()
                self._trip_halt("unexpected_pending_order")
                self.executor.closeout()
                return {"phase": phase.value, "action": "halted_pending_orders"}
            positions = self.exchange.btc_positions()
            active = [p for p in positions if _position_size(p) != 0]
            if active:
                if self.active_since is None:
                    # Unknown opening time after crash/reboot: flatten first.
                    self.halted_session = instant.date()
                    self._trip_halt("untracked_existing_position")
                    self.executor.closeout()
                    return {"phase": phase.value, "action": "halted_orphan_position"}
                if (instant - self.active_since).total_seconds() >= self.config.max_hold_seconds:
                    self.executor.closeout()
                    self.active_since = None
                    return {"phase": phase.value, "action": "time_stop_flat"}
                return {"phase": phase.value, "action": "holding_existing_position"}
            self.active_since = None

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
        if self.config.schedule == "crypto-24x7":
            # The BTC market is continuous regardless of NYSE phase. Retain
            # the NYSE status separately for diagnostics and AI consistency.
            snapshot = dict(snapshot)
            snapshot["nyse_phase"] = snapshot.get("session_phase")
            snapshot["session_phase"] = "trading"
            snapshot["trading_schedule"] = "crypto-24x7"
        context, products = build_ai_context(
            snapshot, max_options=self.config.max_options)
        context["btc_positions"] = positions
        context["open_orders_count"] = 0
        context["trading_schedule"] = self.config.schedule
        context["max_hold_seconds"] = self.config.max_hold_seconds if self.config.schedule == "crypto-24x7" else None
        self.last_ai_utc = instant
        plan = self.planner.propose(
            context, products, recent(self.config.journal_path))
        usage = getattr(self.planner, "last_usage", None)
        model = getattr(self.planner, "model", None)
        trace = getattr(self.planner, "last_request_id", None)
        self._record("ai_decision", {
            "at": instant.isoformat(), "mode": self.config.mode,
            "model": model if isinstance(model, str) else None,
            "gateway_request_id": trace if isinstance(trace, str) else None,
            "ai_tokens": {name: usage[name]
                          for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                          if isinstance(usage, dict) and name in usage},
            "strategy": plan.strategy, "rationale": plan.rationale,
            "legs": [{"product_id": leg.product_id, "side": leg.side,
                      "size": leg.size} for leg in plan.orders],
        })
        if self.config.mode == "observe":
            return {"phase": phase.value, "action": "preview",
                    "strategy": plan.strategy, "legs": len(plan.orders)}

        if not plan.orders:
            return {"phase": phase.value, "action": "wait", "strategy": plan.strategy}
        if self.config.schedule == "crypto-24x7":
            if len(plan.orders) > self.config.max_order_legs or any(
                leg.size > self.config.max_contracts_per_leg for leg in plan.orders
            ):
                self._record("crypto24x7_risk_rejection", {
                    "reason": "pilot_order_quantity_cap",
                    "requested_legs": len(plan.orders),
                    "orders_submitted": False,
                })
                return {"phase": phase.value, "action": "risk_rejected",
                        "orders_submitted": False}
        try:
            # Re-read quotes and demo funds AFTER AI reasoning. This is a
            # preflight sanity check, not a full option-spread margin model.
            check_entry(self.exchange, plan, products, now=self.now(),
                        schedule=self.config.schedule)
            # Requery exchange immediately before posting to avoid known
            # outstanding orders when decisions were being generated.
            if self.exchange.open_orders():
                raise PreflightError("Unexpected pending orders prior to entry")
            self.executor.execute(plan, products)
            if self.config.schedule == "crypto-24x7":
                self.active_since = instant
        except Exception as exc:
            self.halted_session = instant.date()
            self._trip_halt("order_execution_failure")
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

    def _dashboard_heartbeat(self, action: str) -> None:
        """Publish non-secret runtime status for the read-only browser UI."""
        try:
            destination = Path(self.config.journal_path).parent / "runtime.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "mode": self.config.mode,
                "schedule": self.config.schedule,
                "action": str(action)[:80],
                "pid": os.getpid(),
                "environment": "delta-india-demo",
            }
            temporary = destination.with_name(destination.name + "." + str(os.getpid()) + ".tmp")
            handle = os.open(str(temporary), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(state, stream, separators=(",", ":"))
                stream.write("\n")
            os.replace(temporary, destination)
        except OSError:
            # An unavailable dashboard must not compromise exchange safety.
            print("TRADEBOT WARNING: runtime dashboard status write failed",
                  file=sys.stderr, flush=True)

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
                            self._dashboard_heartbeat(result.get("action", "tick"))
                            print(result, flush=True)
                        except KeyboardInterrupt:
                            raise
                        except Exception as exc:
                            self._dashboard_heartbeat("error:" + type(exc).__name__)
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
            self._dashboard_heartbeat("stopped")
            if old_sigterm is not None:
                signal.signal(signal.SIGTERM, old_sigterm)
