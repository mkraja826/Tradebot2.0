"""Independent read-only equity collector and restart-safe operational alerts.

This process cannot submit orders. It stays separate from protective watchdog
work so wallet timeouts / a corrupt equity ledger cannot interrupt SL/TP checks.
Alert events go to the journal and a private SQLite outbox; delivery to an
off-machine pager remains an operator commissioning requirement.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from uuid import uuid4

from tradebot.delta import DeltaDemo, DeltaReadError
from tradebot.equity_receipt import EquityReadError
from tradebot.portfolio_equity_guard import PortfolioEquityGuard, EquityRiskError, stamp

SERVICES = {"watchdog", "equity_collector"}
READ_FAILURES = {
    "broker_authentication_failed", "broker_equity_unavailable", "broker_equity_rejected",
    "broker_time_evidence_unavailable", "equity_read_receipt_missing",
    "equity_read_receipt_invalid", "equity_read_value_mismatch", "system_clock_jump",
    "broker_equity_read_slow", "broker_clock_or_stale_response",
    "broker_equity_response_cached", "broker_equity_read_stale", "equity_boundary_ambiguous",
    "clock_unverified",
}
ALERTS = READ_FAILURES | {
    "equity_database_integrity_failed", "equity_evidence_unavailable",
    "equity_loss_limit_breached", "system_clock_unverified", "equity_ledger_unavailable",
    "missed_daily_checkpoint", "missed_weekly_checkpoint", "signed_equity_observation_stale",
    "equity_ledger_integrity_failed", "equity_clock_inconsistent",
    "operations_evidence_unavailable", "operations_clock_inconsistent",
    "watchdog_heartbeat_stale", "equity_collector_heartbeat_stale",
    "watchdog_restart_loop", "equity_collector_restart_loop", "watchdog_protection_unverified",
}


class MonitorStore:
    """Separate from immutable risk evidence; short transactions, bounded waits."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS monitor_heartbeat(
                    service TEXT PRIMARY KEY, checked_us INTEGER NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS monitor_starts(
                    instance TEXT PRIMARY KEY, service TEXT NOT NULL, started_us INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS monitor_start_time ON monitor_starts(service,started_us);
                CREATE TABLE IF NOT EXISTS monitor_alert_state(
                    code TEXT PRIMARY KEY, active INTEGER NOT NULL, last_emitted_us INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS monitor_events(
                    id INTEGER PRIMARY KEY, at_us INTEGER NOT NULL, code TEXT NOT NULL,
                    transition TEXT NOT NULL, severity TEXT NOT NULL);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=1)

    def start(self, service, *, at=None, instance=None):
        if service not in SERVICES:
            raise ValueError("Unknown service")
        with closing(self.connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO monitor_starts VALUES (?,?,?)",
                       (instance or uuid4().hex, service, stamp(at or datetime.now(timezone.utc))))

    def heartbeat(self, service, status="healthy", *, at=None):
        if service not in SERVICES or status not in ALERTS | {"healthy"}:
            raise ValueError("Unknown service state")
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO monitor_heartbeat VALUES (?,?,?) "
                       "ON CONFLICT(service) DO UPDATE SET checked_us=excluded.checked_us, "
                       "status=excluded.status",
                       (service, stamp(at or datetime.now(timezone.utc)), status))

    def publish(self, codes, *, at=None):
        """Durably deduplicate active/recovered events, including concurrent runs."""
        codes = set(codes)
        if not codes <= ALERTS:
            raise ValueError("Unknown alert code")
        now_us = stamp(at or datetime.now(timezone.utc))
        events = []
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = {code: (active, emitted) for code, active, emitted in db.execute(
                "SELECT code,active,last_emitted_us FROM monitor_alert_state")}
            for code in sorted(codes | previous.keys()):
                old, emitted = previous.get(code, (0, 0))
                active = int(code in codes)
                changed = old != active
                if not changed and not (active and now_us - emitted >= 300_000_000):
                    continue
                transition = "resolved" if not active else "opened" if changed else "reminder"
                severity = "info" if not active else (
                    "warning" if code.startswith("missed_") or code == "equity_boundary_ambiguous"
                    else "critical")
                db.execute("INSERT INTO monitor_alert_state VALUES (?,?,?) "
                           "ON CONFLICT(code) DO UPDATE SET active=excluded.active, "
                           "last_emitted_us=excluded.last_emitted_us", (code, active, now_us))
                cursor = db.execute("INSERT INTO monitor_events(at_us,code,transition,severity) "
                                    "VALUES (?,?,?,?)", (now_us, code, transition, severity))
                events.append({"event": "equity_safety_incident", "id": cursor.lastrowid,
                               "code": code, "transition": transition, "severity": severity,
                               "at_us": now_us})
            db.commit()
        return events


def operations_health(path, *, at=None):
    now_us = stamp(at or datetime.now(timezone.utc))
    report = {"watchdog": "unavailable", "equity_collector": "unavailable",
              "alert_codes": [], "mode": "read_only"}
    try:
        path = Path(path)
        if not path.is_file() or path.is_symlink():
            raise ValueError("Unavailable")
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise ValueError("Integrity failure")
            for service in sorted(SERVICES):
                row = db.execute("SELECT checked_us,status FROM monitor_heartbeat WHERE service=?",
                                 (service,)).fetchone()
                if row and (type(row[0]) is not int or row[0] > now_us):
                    report["alert_codes"].append("operations_clock_inconsistent")
                    raise ValueError("Future heartbeat")
                max_age = 90 if service == "watchdog" else 180
                age = (now_us - row[0]) / 1_000_000 if row else None
                report[service + "_age_seconds"] = age
                if age is None or age > max_age:
                    report[service] = "stale"
                    report["alert_codes"].append(service + "_heartbeat_stale")
                elif row[1] not in ALERTS | {"healthy"}:
                    raise ValueError("Unknown service state")
                else:
                    report[service] = row[1]
                    if row[1] != "healthy":
                        report["alert_codes"].append(row[1])
                count = db.execute("SELECT count(*) FROM monitor_starts WHERE service=? "
                                   "AND started_us>=? AND started_us<=?",
                                   (service, now_us - 600_000_000, now_us)).fetchone()[0]
                if count >= 3:
                    report["alert_codes"].append(service + "_restart_loop")
    except (sqlite3.Error, OSError, ValueError, TypeError):
        report.update(watchdog="unavailable", equity_collector="unavailable",
                      alert_codes=sorted(set(report["alert_codes"]) | {"operations_evidence_unavailable"}))
    return report


def risk_health(path, *, at=None):
    from tradebot.equity_checkpoint_health import checkpoint_health
    now = at or datetime.now(timezone.utc)
    report = checkpoint_health(path, at=now)
    report["monitoring"] = operations_health(Path(path).with_name("fire-monitoring.sqlite"), at=now)
    codes = report["monitoring"]["alert_codes"]
    if codes:
        report["blocking_conditions"] = sorted(set(report["blocking_conditions"]) | set(codes))
        report["alert_codes"] = sorted(set(report["alert_codes"]) | set(codes))
        report["checkpoint_prerequisites_met"] = False
        if report["status"] == "healthy":
            report["status"] = "monitoring_degraded"
    return report


def clock_synchronized():
    """Read-only bounded OS check. Unknown is not confirmation of correct UTC."""
    try:
        result = subprocess.run(["timedatectl", "show", "--property=NTPSynchronized", "--value"],
                                capture_output=True, text=True, timeout=2, check=False)
        return result.returncode == 0 and result.stdout.strip() == "yes"
    except (OSError, subprocess.TimeoutExpired):
        return False


def collect_once(exchange, data_dir, *, clock_check=clock_synchronized):
    """No orders, no AI, one signed wallet GET at most; no automatic retries."""
    path = Path(data_dir) / "fire-equity-risk.sqlite"
    status = "healthy"
    try:
        if not clock_check():
            raise EquityReadError("system_clock_unverified")
        result = PortfolioEquityGuard(path).observe_signed_demo(exchange)
        if result["reason"].startswith("loss_limit_"):
            status = "equity_loss_limit_breached"
    except (EquityReadError, DeltaReadError) as exc:
        status = exc.code if exc.code in ALERTS else "equity_evidence_unavailable"
    except (sqlite3.Error, EquityRiskError):
        status = "equity_database_integrity_failed"
    except Exception:
        status = "equity_evidence_unavailable"
    store = MonitorStore(Path(data_dir) / "fire-monitoring.sqlite")
    store.heartbeat("equity_collector", status)
    report = risk_health(path)
    return report, store.publish(report["alert_codes"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--check", action="store_true", help="Read existing health only; no broker calls")
    args = parser.parse_args(argv)
    if args.check:
        report = risk_health(Path(args.data_dir) / "fire-equity-risk.sqlite")
        print(json.dumps(report))
        return 0 if report["checkpoint_prerequisites_met"] else 2
    exchange = DeltaDemo(api_key=os.environ.get("DELTA_DEMO_API_KEY", ""),
                         api_secret=os.environ.get("DELTA_DEMO_API_SECRET", ""), allow_orders=False)
    started = False
    while True:
        tick = time.monotonic()
        try:
            if not started:
                MonitorStore(Path(args.data_dir) / "fire-monitoring.sqlite").start("equity_collector")
                started = True
            _, events = collect_once(exchange, args.data_dir)
            for event in events:
                print(json.dumps(event), flush=True)
        except Exception:
            # The operational outbox itself is broken. A bounded once-per-minute
            # fallback avoids leaking exception messages / credentials.
            print(json.dumps({"event": "equity_safety_incident", "severity": "critical",
                              "code": "operations_evidence_unavailable"}), flush=True)
        time.sleep(max(1, 60 - (time.monotonic() - tick)))


if __name__ == "__main__":
    raise SystemExit(main())
