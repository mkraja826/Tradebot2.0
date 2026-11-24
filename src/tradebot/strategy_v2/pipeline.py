"""Strategy V2: public candle -> independent signals -> durable AI candidate.

SHADOW MODE ONLY. The existing broker execution and risk systems are untouched.
"""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import time

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.multi_strategy_signals import MARKETS, scan_completed_5m
from tradebot.signal_ai_router import build_ai_signal_event
from tradebot.strategy_v2.journal import SignalJournal
from tradebot.strategy_v2.ai_context import build_model_context

DEFAULT_JOURNAL_DIR = Path("data/strategy-v2")


def inspect_symbol(client, symbol, *, as_of, journal):
    """Produce and persist a qualifying AI candidate, without dispatching it."""
    if (symbol not in MARKETS or getattr(client, "base_url", None) != DEMO_API
            or getattr(client, "allow_orders", None) is not False):
        raise ValueError("read_only_demo_market_required")
    candles = client.candles(
        symbol=symbol, resolution="5m", start=as_of-300*300, end=as_of)
    completed = [c for c in candles
                 if isinstance(c, dict) and type(c.get("time")) is int
                 and c["time"]+300 <= as_of]
    completed.sort(key=lambda c: c["time"])
    scan = scan_completed_5m(completed[-250:], symbol, as_of=as_of)
    routed = build_ai_signal_event(scan)
    status = "no_qualifying_signal"
    context_hash = None
    if routed["dispatch_ai"]:
        model_context = build_model_context(routed, completed[-250:])
        context_hash = sha256(json.dumps(
            model_context, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        result = journal.observe(routed)
        status = result["status"]
    return {
        "symbol": symbol, "status": status,
        "model_if_enabled": routed.get("model"),
        "event_id": routed["event_id"],
        "candle_time": scan["candle_time"],
        "candidate_count": scan["candidate_count"],
        "conflicting_directions": scan["conflicting_directions"],
        "ai_candidate_recorded": routed["dispatch_ai"]
            and status == "new_signal_observed",
        "ai_dispatched": False,
        "model_context_ready": context_hash is not None,
        "model_context_hash": context_hash,
        "broker_orders_submitted": 0,
        "execution_authorized": False,
    }


def _private_journal_dir(path):
    root = Path(path)
    if root.is_symlink():
        raise ValueError("shadow_journal_symlink")
    if not root.exists():
        root.mkdir(parents=True, mode=0o700)
    return root


def run_shadow_once(*, client=None, now=None, journal_dir=DEFAULT_JOURNAL_DIR):
    """Every market independently scanned; invalid data never halts other market."""
    stamp = int(time.time()) if now is None else now
    if type(stamp) is not int or stamp <= 0:
        raise ValueError("invalid_monitor_time")
    boundary = stamp//300*300
    # Read-only demo market feed: account actions remain unavailable.
    broker = client if client is not None else DeltaDemo(
        "", "", allow_orders=False)
    journal = SignalJournal(_private_journal_dir(journal_dir)
                            / "signal-observations.sqlite")
    results = []
    for symbol in ("BTCUSD","XAUTUSD"):
        try:
            results.append(inspect_symbol(
                broker, symbol, as_of=boundary, journal=journal))
        except Exception as exc:
            results.append({
                "symbol":symbol, "status":"shadow_scan_unavailable",
                "error_type":type(exc).__name__,
                "ai_dispatched":False,
                "broker_orders_submitted":0,
                "execution_authorized":False,
            })
    return {
        "mode":"STRATEGY_V2_SHADOW",
        "as_of":boundary,
        "signal_rule":"one_of_ten",
        "ai_requests":0, "broker_mutations":0,
        "events_recorded":journal.count(), "markets":results,
    }


def main():
    print(json.dumps(run_shadow_once(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

