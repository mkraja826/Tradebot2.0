"""Continuous BTC/Gold demo-only service. Default mode scans without AI or orders."""
import argparse
import json
import math
import os
import signal
import threading
import time
from pathlib import Path
from .broker import DeltaDemo
from .decision import DecisionJournal, Provider, configured_models
from .engine import Journal
from .execution import DemoExecutor, evaluate_and_execute
from .scanner import scan_once
from .direction import direction_for
from .research import SignalResearch
from .opportunity import opportunity
from .planner_shadow import packet,load_reference,ShadowJournal
from .lifecycle import Lifecycle
from tradebot.market_data_v3 import MARKETS

PREFIX = {"BTCUSD": "RECOVER_BTC", "XAUTUSD": "RECOVER_GOLD"}

def credentials(symbol, env):
    prefix = PREFIX[symbol]
    key, secret = env.get(prefix + "_DEMO_KEY"), env.get(prefix + "_DEMO_SECRET")
    if not key or not secret:
        raise ValueError("Missing demo credentials for " + symbol)
    return key, secret

def emit(event):
    print(json.dumps(event, allow_nan=False, separators=(",", ":")), flush=True)

class MarketService:
    def __init__(self, symbol, directory, *, model="", provider=None, broker=None,
                 scan=scan_once, output=emit):
        if symbol not in PREFIX:
            raise ValueError("Unsupported market")
        self.symbol = symbol
        self.directory = Path(directory) / symbol
        self.directory.mkdir(parents=True, exist_ok=True)
        self.model, self.provider, self.broker = model, provider, broker
        self.scan, self.output = scan, output
        if broker is not None and (provider is None or not model):
            raise ValueError("Execution requires configured AI")
        self.decisions = self.orders = self.executor = self.lifecycle = None

    def open(self):
        self.research = SignalResearch(self.directory / "signal_research.sqlite")
        self.planner = ShadowJournal(self.directory / "planner_shadow.sqlite")
        if self.broker is not None:
            self.decisions = DecisionJournal(self.directory / "decisions.sqlite")
            self.orders = Journal(self.directory / "orders.sqlite")
            self.executor = DemoExecutor(self.broker, self.orders)
            self.lifecycle = Lifecycle(self.broker, self.orders)

    def close(self):
        if self.orders is not None:
            self.orders.close()
        self.executor = self.orders = self.decisions = self.lifecycle = None

    def publish(self, event):
        # Atomic replacement keeps dashboard reads independent of worker writes.
        temporary = self.directory / "status.tmp"
        temporary.write_text(json.dumps(event, allow_nan=False), encoding="utf-8")
        temporary.replace(self.directory / "status.json")
        self.output(event)

    def cycle(self):
        if self.broker is not None and self.executor is None:
            raise RuntimeError("Open execution journals first")
        reconciliation_error = None
        if self.executor is not None:
            try:
                self.executor.reconcile()
            except Exception as exc:
                reconciliation_error = type(exc).__name__
        lifecycle = {}
        if self.lifecycle is not None:
            try:
                lifecycle = self.lifecycle.refresh(self.symbol)
            except Exception as exc:
                lifecycle = {"errors": {"refresh": type(exc).__name__}}
        report = self.scan(self.directory / "market.sqlite", symbols=(self.symbol,),
                           include_context=True)["markets"][self.symbol]
        direction = None
        research = None
        evidence = None
        planner = None
        if report.get("status") != "scan_error":
            direction = direction_for(report)
            try:
                evidence = opportunity(report,direction)
            except Exception as exc:
                evidence = {"status":"evidence_error","error":type(exc).__name__}
            try:
                research = self.research.record(report,direction)
            except Exception as exc:
                research = {"status":"research_error","error":type(exc).__name__}
        if report.get("status") != "scan_error":
            try:
                reference=load_reference(self.directory / "planner_reference.json")
                planner=self.planner.record(packet(report,direction,reference))
            except Exception as exc:
                planner={"status":"shadow_error","error":type(exc).__name__,"execution_effect":"none"}
        if report.get("status") == "scan_error":
            result = {"status": "scan_error", "reason": report.get("reason")}
        elif self.executor is None:
            result = {"status": "preview", "signals": report["signals"], "ai_calls": 0}
        else:
            result = evaluate_and_execute(report, self.decisions, self.provider,
                                          {self.symbol: self.model}, self.executor)
        # Full decision context and exchange receipts are stored in the journals.
        # Emit only operational metadata; never print account or credential contents.
        summary = result.get("decision", result)
        execution = result.get("execution", {})
        event = {"symbol": self.symbol, "mode": "demo" if self.executor else "preview",
                 "timestamp": int(time.time()), "status": summary.get("status"),
                 "ai_calls": summary.get("ai_calls", 0),
                 "decision_id": summary.get("decision_id"),
                 "execution_status": execution.get("status"),
                 "client_id": execution.get("client_id"),
                 "signal_count": len(report.get("signals", [])),
                 "coverage": report.get("coverage", {}),
                 "direction_engine": direction,
                 "research": research,
                 "opportunity": evidence,
                 "planner_shadow": planner,
                 "error": summary.get("error", summary.get("reason")),
                 "reconciliation_error": reconciliation_error,
                 "lifecycle": {"new_fills": lifecycle.get("new_fills"),
                               "bracket_evidence": lifecycle.get("bracket_evidence"),
                               "errors": lifecycle.get("errors", {})}}
        self.publish(event)
        return event

    def run(self, stop, interval, *, once=False):
        try:
            self.open()
            while not stop.is_set():
                started = time.monotonic()
                try:
                    self.cycle()
                except Exception as exc:
                    self.publish({"symbol": self.symbol, "status": "cycle_error",
                                 "error": type(exc).__name__, "timestamp": int(time.time())})
                if once:
                    break
                stop.wait(max(0, interval - (time.monotonic() - started)))
        finally:
            self.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/recover-service")
    parser.add_argument("--symbol", choices=MARKETS, action="append")
    parser.add_argument("--interval", type=float, default=60, help="Target scan interval in seconds")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--execute-demo", action="store_true", help="Enable billable AI and demo orders")
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("Interval must be finite and positive")
    symbols = tuple(dict.fromkeys(args.symbol or MARKETS))
    models = configured_models()
    accounts = {}
    if args.execute_demo:
        if not os.environ.get("TB_API_KEY") or any(not models[s] for s in symbols):
            parser.error("Configure TB_API_KEY and selected market models")
        try:
            accounts = {s: credentials(s, os.environ) for s in symbols}
        except ValueError as exc:
            parser.error(str(exc))
        if len({v[0] for v in accounts.values()}) != len(accounts):
            parser.error("Provide distinct demo API keys for the selected markets")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    output_lock = threading.Lock()
    def output(event):
        with output_lock:
            emit(event)
    services = [MarketService(s, args.data_dir, model=models[s],
                              broker=DeltaDemo(*accounts[s]) if args.execute_demo else None,
                              provider=Provider() if args.execute_demo else None,
                              output=output) for s in symbols]
    failures = []
    def worker(service):
        try:
            service.run(stop, args.interval, once=args.once)
        except Exception as exc:
            failures.append(service.symbol)
            output({"symbol": service.symbol, "status": "worker_failed", "error": type(exc).__name__})
    threads = [threading.Thread(target=worker, args=(s,), name=s.symbol) for s in services]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return int(bool(failures))

if __name__ == "__main__":
    raise SystemExit(main())
