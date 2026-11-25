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
from .bracket_repair import BracketRepair
from .management_shadow import ManagementShadow
from .open_excursion import report as open_excursion_report
from .management_executor import ManagementExecutor
from .execution import product_for
from .market_quality import diagnostics
from .department_feedback import attach
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
                 scan=scan_once, output=emit, manage_demo=False, learning_journal=None):
        if symbol not in PREFIX:
            raise ValueError("Unsupported market")
        self.symbol = symbol
        self.directory = Path(directory) / symbol
        self.directory.mkdir(parents=True, exist_ok=True)
        self.model, self.provider, self.broker = model, provider, broker
        self.scan, self.output = scan, output
        self.manage_demo=manage_demo
        self.learning_journal=learning_journal
        self.management_executor=None
        if broker is not None and (provider is None or not model):
            raise ValueError("Execution requires configured AI")
        self.decisions = self.orders = self.executor = self.lifecycle = self.repair = self.management = None

    def open(self):
        self.research = SignalResearch(self.directory / "signal_research.sqlite")
        self.planner = ShadowJournal(self.directory / "planner_shadow.sqlite")
        if self.broker is not None:
            self.decisions = DecisionJournal(self.directory / "decisions.sqlite")
            self.orders = Journal(self.directory / "orders.sqlite")
            self.executor = DemoExecutor(self.broker, self.orders)
            self.lifecycle = Lifecycle(self.broker, self.orders)
            self.repair = BracketRepair(self.broker,self.orders)
            self.management = ManagementShadow(self.orders.db)
            self.management_executor=ManagementExecutor(self.broker,self.orders)

    def close(self):
        if self.orders is not None:
            self.orders.close()
        self.executor = self.orders = self.decisions = self.lifecycle = self.repair = None

    def publish(self, event):
        # Atomic replacement keeps dashboard reads independent of worker writes.
        temporary = self.directory / "status.tmp"
        temporary.write_text(json.dumps(event, allow_nan=False), encoding="utf-8")
        temporary.replace(self.directory / "status.json")
        self.output(event)

    def cycle(self):
        started=time.monotonic()
        if self.broker is not None and self.executor is None:
            raise RuntimeError("Open execution journals first")
        reconciliation_error = None
        # Lifecycle.refresh now performs the single scheduled reconciliation pass.
        lifecycle = {}
        if self.lifecycle is not None:
            try:
                lifecycle = self.lifecycle.refresh(self.symbol)
            except Exception as exc:
                lifecycle = {"errors": {"refresh": type(exc).__name__}}
        management_reconciliation=None
        if self.manage_demo and self.management_executor is not None:
            try:management_reconciliation=self.management_executor.reconcile_pending(self.symbol)
            except Exception as exc:management_reconciliation={"status":"reconciliation_error","error":type(exc).__name__,"execution_effect":"none"}
        repair = self.repair.cycle(self.symbol,lifecycle) if self.repair is not None else None
        lifecycle_ms=round((time.monotonic()-started)*1000)
        scan_started=time.monotonic()
        report = self.scan(self.directory / "market.sqlite", symbols=(self.symbol,),
                           include_context=True)["markets"][self.symbol]
        scan_ms=round((time.monotonic()-scan_started)*1000)
        report=attach(report,self.learning_journal)
        quality=None
        if report.get("status") != "scan_error":
            try:quality=diagnostics(report,self.directory / "market.sqlite")
            except Exception as exc:quality={"status":"diagnostics_error","error":type(exc).__name__,"execution_effect":"none"}
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
        excursion=open_excursion_report(self.directory,self.symbol,lifecycle,int(time.time())) if self.lifecycle is not None else None
        management=None
        if self.management is not None and report.get("status")!="scan_error":
            try:management=self.management.capture(report,lifecycle,self.model,lambda s:product_for(self.broker,s),excursion=excursion)
            except Exception as exc:management={"status":"capture_error","error":type(exc).__name__,"execution_effect":"none"}
        managed={"status":"execution_disabled" if not self.manage_demo else "awaiting_next_sample","enabled":self.manage_demo,"attempted":False}
        if self.manage_demo and management:
            captured=management.get("status")
            if captured=="failed":managed["status"]="evaluation_failed"
            elif captured=="proposed":managed["status"]="proposal_already_evaluated"
            elif captured in ("context_unavailable","capture_error","no_fresh_position","requested"):managed["status"]=captured
        # Explicit opt-in. Only newly captured, current proposals can execute.
        if self.manage_demo and management and management.get("status")=="prepared" and management.get("context_bytes"):
            try:
                ident=management["id"]
                outcome=self.management.evaluate(ident,self.provider)
                managed=self.management_executor.execute(self.symbol,ident,enabled=True) if outcome["status"]=="proposed" else {"status":outcome["status"],"attempted":False,"error":outcome.get("error"),"response_error":outcome.get("response_error")}
                managed["management_ai_calls"]=1
                managed["enabled"]=True
            except Exception as exc:managed={"status":"management_error","error":type(exc).__name__,"attempted":False}
        execution_started=time.monotonic()
        if report.get("status") == "scan_error":
            result = {"status": "scan_error", "reason": report.get("reason")}
        elif self.executor is None:
            result = {"status": "preview", "signals": report["signals"], "ai_calls": 0}
        elif self.manage_demo and (managed.get("attempted") or lifecycle.get("positions") or "positions" not in lifecycle):
            result={"status":"position_management_cycle","ai_calls":0}
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
                 "market_quality": quality,
                 "cycle_timing_ms":{"lifecycle":lifecycle_ms,"scan":scan_ms,"decision_execution":round((time.monotonic()-execution_started)*1000),"total":round((time.monotonic()-started)*1000)},
                 "planner_shadow": planner,
                 "bracket_repair": repair,
                 "management_shadow": management,
                 "open_excursion":excursion,
                 "management_execution": managed,
                 "management_reconciliation": management_reconciliation,
                 "error": summary.get("error", summary.get("reason")),
                 "reconciliation_error": reconciliation_error,
                 "lifecycle": {"new_fills": lifecycle.get("new_fills"),
                               "bracket_evidence": lifecycle.get("bracket_evidence"),
                               "errors": lifecycle.get("errors", {}), "order_poll_schedule":lifecycle.get("order_poll_schedule")}}
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
    parser.add_argument("--manage-demo",action="store_true",help="Enable recurring AI management and demo position mutations")
    args = parser.parse_args()
    parser.add_argument("--learning-journal", help="Opt-in read-only prior outcome evidence for AI context")
    if args.manage_demo and not args.execute_demo:parser.error("--manage-demo requires --execute-demo")
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
                              output=output,manage_demo=args.manage_demo,learning_journal=args.learning_journal) for s in symbols]
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
