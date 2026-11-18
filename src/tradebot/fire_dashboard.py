"""User-initiated, read-only FIRE commissioning for the private dashboard.

No exchange-order execution: this module only invokes the existing Top Billing
Kimi + GPT-6 comparison probe, using one common authenticated BTC snapshot.
Invocations cost model credits; there is no scheduled or automatic activation.
"""
from datetime import datetime, timezone
from threading import Lock, Thread
from time import monotonic

from tradebot.fire_probe import ROLES, run_probe, load_snapshot


class FirePreviewController:
    def __init__(self, *, probe=run_probe, snapshot_loader=load_snapshot,
                 cooldown_seconds=300, clock=monotonic):
        self._probe = probe
        self._snapshot_loader = snapshot_loader
        self._clock = clock
        self._cooldown = max(300, int(cooldown_seconds))
        self._lock = Lock()
        self._started = None
        self._state = {
            "status": "idle", "mode": "read_only_research",
            "orders_submitted": False, "paid_model_calls_possible": True,
            "models": dict(ROLES),
        }

    def snapshot(self):
        with self._lock:
            remaining = 0 if self._started is None else max(
                0, int(self._cooldown - (self._clock() - self._started) + 0.999))
            return {**self._state, "cooldown_seconds": remaining}

    def start(self):
        with self._lock:
            if self._state["status"] == "running":
                return False, "already_running"
            if (self._started is not None and
                    self._clock() - self._started < self._cooldown):
                return False, "cooldown_active"
            self._started = self._clock()
            self._state = {
                "status": "running", "mode": "read_only_research",
                "orders_submitted": False, "paid_model_calls_possible": True,
                "models": dict(ROLES),
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        Thread(target=self._run, daemon=True).start()
        return True, "started"

    def _run(self):
        try:
            report = self._probe(dict(ROLES), self._snapshot_loader)
            result = {
                "snapshot_at": str(report.get("collected_at") or "")[:40],
                "snapshot_sha256": str(report.get("snapshot_sha256") or "")[:64],
                "results": {},
            }
            for role, model in ROLES.items():
                upstream = (report.get("results") or {}).get(role) or {}
                row = {"model": model}
                if "decision" in upstream:
                    plan = upstream["decision"]
                    row["decision"] = {
                        "direction": plan["direction"],
                        "contracts": plan["contracts"],
                        "stop_loss": plan["stop_loss"],
                        "take_profit": plan["take_profit"],
                    }
                else:
                    # Never return raw model content, provider errors, or
                    # upstream request IDs from a browser-facing API.
                    row["error"] = "No valid decision from this model"
                if type(upstream.get("latency_ms")) is int:
                    row["latency_ms"] = upstream["latency_ms"]
                usage = upstream.get("usage")
                if isinstance(usage, dict):
                    row["tokens"] = {
                        key: usage[key] for key in (
                            "prompt_tokens", "completion_tokens", "total_tokens")
                        if type(usage.get(key)) is int
                    }
                result["results"][role] = row
            update = {"status": "completed", "result": result}
        except Exception:
            # No secrets, prompts, exceptions or raw response bodies in UI.
            update = {
                "status": "failed",
                "error": "Unable to complete BTC snapshot/model comparison; check VM logs",
            }
        with self._lock:
            self._state = {
                **self._state, **update, "orders_submitted": False,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
