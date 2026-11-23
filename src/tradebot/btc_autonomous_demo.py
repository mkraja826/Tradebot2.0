"""Bounded BTCUSD Delta India DEMO-only unattended pilot.

Runs read-only eligibility checks every five minutes and may reserve at most
two GPT-6 FIRE attempts per UTC day, four hours apart. Broker risk/protection
checks remain inside SupervisedBTCController. No production host is supported.
"""
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
from uuid import uuid4
import json
from decimal import Decimal
import os
import sqlite3
import stat
import time

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.btc_supervised_execution import SupervisedBTCController
from tradebot.btc_supervised_equity_guard import SupervisedSessionEquityGuard
from tradebot.portfolio_equity_guard import EquityRiskError, amount
from tradebot.fire_btc_supervised_commission import readonly_btc_commission_preflight

ARM_CONTENT = "DELTA-INDIA-DEMO:BTCUSD:UNATTENDED:MAX2-UTC-DAY"
MAX_DAILY_ATTEMPTS = 2
MIN_INTERVAL = 4 * 3600
POLL_SECONDS = 300
TERMINAL_SAFE = {"rejected_no_order", "flat_verified"}


def arm_path():
    return Path.home() / ".config" / "tradebot2" / "btc-auto-demo-armed"


def is_armed(path=None):
    """An explicit 0600 owner-owned file, never an environment-variable flag."""
    source = Path(path) if path is not None else arm_path()
    try:
        if source.is_symlink() or not source.is_file():
            return False
        fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            mode = os.fstat(fd)
            if not stat.S_ISREG(mode.st_mode) or stat.S_IMODE(mode.st_mode) != 0o600:
                return False
            if mode.st_uid != os.geteuid() or mode.st_size > 100:
                return False
            content = os.read(fd, 101)
        finally:
            os.close(fd)
        return content == (ARM_CONTENT + "\n").encode()
    except OSError:
        return False


MAX_DAILY_EQUITY_DECLINE = Decimal("0.005")


def check_daily_equity_limit(root, now, current):
    """Original broker receipt is verified by caller; persist earliest UTC baseline."""
    current = amount(current)
    if current <= 0:
        raise EquityRiskError("btc_auto_daily_equity_unverified")
    dbpath=Path(root)/"btc-auto-demo.sqlite"
    if dbpath.is_symlink():
        raise EquityRiskError("btc_auto_equity_ledger_untrusted")
    day=now.astimezone(timezone.utc).date().isoformat()
    with closing(_connect(dbpath)) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS btc_auto_daily_equity(
            utc_day TEXT PRIMARY KEY, starting_equity TEXT NOT NULL)""")
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT starting_equity FROM btc_auto_daily_equity "
                       "WHERE utc_day=?",(day,)).fetchone()
        if row is None:
            db.execute("INSERT INTO btc_auto_daily_equity VALUES (?,?)",
                       (day,str(current)))
            baseline=current
        else:
            baseline=amount(row[0])
        if baseline<=0:
            raise EquityRiskError("btc_auto_daily_baseline_invalid")
        if (baseline-current)/baseline >= MAX_DAILY_EQUITY_DECLINE:
            raise EquityRiskError("btc_auto_daily_loss_limit")
        db.commit()


class AutoDailyEquityGuard(SupervisedSessionEquityGuard):
    """Unattended attempts share a durable day-long 0.5% decline ceiling."""
    def require_verified_read(self, equity, receipt, *, now=None):
        verdict=super().require_verified_read(equity,receipt,now=now)
        instant=now or datetime.now(timezone.utc)
        check_daily_equity_limit(self.path.parent,instant,equity)
        return {**verdict,"autonomous_daily_equity_limit":"0.5_percent"}


class AutoBTCController(SupervisedBTCController):
    def __init__(self,path,*,enabled=False,**kwargs):
        super().__init__(path,enabled=enabled,**kwargs)
        self.equity_guard = AutoDailyEquityGuard(
            self.path.parent/"fire-equity-risk.sqlite")

    def _require_account_flat(self, exchange, product_id):
        if not is_armed():
            raise ValueError("autonomous_demo_disarmed")
        return super()._require_account_flat(exchange, product_id)

    def _max_contracts_for_entry(self, budget):
        return min(1,super()._max_contracts_for_entry(budget))

    def _additional_fire_scope(self):
        return {
            "strategy_history_version": "btc-demo-recent24h-v1",
            "unattended_demo_mode": True,
            "max_contracts_per_entry": 1,
            "one_attempt_operator_supervision_required": False,
            "max_new_order_attempts_per_utc_day": MAX_DAILY_ATTEMPTS,
        }


def _connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("""CREATE TABLE IF NOT EXISTS btc_auto_attempts(
        attempt_id TEXT PRIMARY KEY, utc_day TEXT NOT NULL,
        requested_at INTEGER NOT NULL, status TEXT NOT NULL)""")
    return db


def claim_attempt(data_dir, instant):
    """Durable charge-before-AI admission; never refund an ambiguous attempt."""
    ts = int(instant.timestamp())
    day = instant.date().isoformat()
    with closing(_connect(Path(data_dir) / "btc-auto-demo.sqlite")) as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute(
            "SELECT requested_at FROM btc_auto_attempts "
            "ORDER BY requested_at DESC LIMIT 1").fetchone()
        used = db.execute(
            "SELECT COUNT(*) FROM btc_auto_attempts WHERE utc_day=?", (day,)).fetchone()[0]
        if used >= MAX_DAILY_ATTEMPTS or (old and ts-old[0] < MIN_INTERVAL):
            db.rollback()
            return None
        entry_id = uuid4().hex
        db.execute("INSERT INTO btc_auto_attempts VALUES (?,?,?,?)",
                   (entry_id, day, ts, "reserved_before_model"))
        db.commit()
        return entry_id


def set_attempt_status(data_dir, entry_id, status):
    with closing(_connect(Path(data_dir) / "btc-auto-demo.sqlite")) as db:
        db.execute("UPDATE btc_auto_attempts SET status=? WHERE attempt_id=?",
                   (status,entry_id))
        db.commit()


def check_candidate(data_dir, *, broker_factory=DeltaDemo,
                    preflight=readonly_btc_commission_preflight):
    """Fresh authenticated read-only gate; no order authority by itself."""
    # DeltaDemo does not read credentials from environment by itself.
    # Supply them only to the readonly instance (never stored or reported).
    broker = broker_factory(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False)
    if getattr(broker, "base_url", None) != DEMO_API or broker.allow_orders is not False:
        return False
    r = preflight(broker, Path(data_dir))
    return (
        type(r) is dict
        and r.get("status") == "operator_review_candidate_only"
        and r.get("blockers") == []
        and r.get("supervised_session_verified") is True
        and r.get("recent_btc_history_local_quality_verified") is True
        and r.get("signed_isolated_margin_verified") is False
        and r.get("owner_declared_main_isolated_accepted") is True
        and r.get("account_wide_flatness_verified") is True
        and r.get("watchdog_and_collector_active") is True
        and r.get("both_dashboard_fire_endpoints_disabled") is True
        and r.get("trade_authorized") is False
    )


def prior_fire_receipts_safe(root):
    """Never auto-retry an unresolved/error FIRE after a process restart."""
    path=Path(root)/"fire-ops.sqlite"
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with closing(sqlite3.connect(
                path.absolute().as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            all_statuses=db.execute(
                "SELECT DISTINCT status FROM fire_requests").fetchall()
            if any(row[0] not in TERMINAL_SAFE for row in all_statuses):
                return False
            last=db.execute(
                "SELECT status,result FROM fire_requests "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
            if last is None:
                return True
            detail=json.loads(last[1])
            if type(detail) is not dict:
                return False
            if last[0]=="rejected_no_order":
                return detail.get("reason_code")=="gpt6_wait_no_trade"
            return (last[0]=="flat_verified"
                    and detail.get("reason_code") not in (
                        "emergency_flat_verified","execution_or_protection_unverified"))
    except (sqlite3.Error,OSError,ValueError,TypeError):
        return False


def run_once(data_dir, *, instant=None, armed=is_armed,
             candidate=check_candidate, controller_factory=AutoBTCController,
             receipts_safe=prior_fire_receipts_safe, do_execute=False):
    """The default is read-only. The service requires its private arm file."""
    now = instant or datetime.now(timezone.utc)
    root = Path(data_dir)
    if not root.is_dir() or root.is_symlink() or now.tzinfo is None:
        return {"status":"blocked","reason":"invalid_root_or_clock"}
    if not armed():
        return {"status":"disarmed"}
    if (root / "btc-auto-demo-halt").exists():
        return {"status":"halted_pending_operator_review"}
    try:
        eligible = candidate(root)
    except Exception:
        eligible = False
    if not eligible:
        return {"status":"read_only_preflight_unavailable"}
    if not receipts_safe(root):
        return {"status":"previous_fire_decision_or_execution_unresolved"}
    if not do_execute:
        return {"status":"eligible_read_only_no_order"}
    attempt_id = claim_attempt(root,now)
    if attempt_id is None:
        return {"status":"daily_or_interval_budget_exhausted"}
    try:
        bot = controller_factory(root/"fire-ops.sqlite",enabled=True,
                                 spawn=lambda task:task())
        accepted,reason = bot.start(press=attempt_id)
        receipt = bot.snapshot()
        status = receipt.get("status") if accepted else "start_rejected"
        set_attempt_status(root,attempt_id,status)
        # Every rejection except an explicit GPT-6 WAIT is investigated
        # before another unattended attempt; no fail-open retry loops.
        unexpected_rejection = (
            status == "rejected_no_order"
            and receipt.get("reason_code") != "gpt6_wait_no_trade")
        emergency_closeout = (
            status == "flat_verified"
            and receipt.get("reason_code") in (
                "emergency_flat_verified", "execution_or_protection_unverified"))
        properly_protected = (
            status == "protected_active"
            and receipt.get("protection_verified") is True
            and receipt.get("liquidation_verified") is True)
        if ((status not in TERMINAL_SAFE and not properly_protected)
                or unexpected_rejection or emergency_closeout):
            os.close(os.open(root/"btc-auto-demo-halt",
                             os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600))
        return {"status":"attempt_finished","accepted":bool(accepted),
                "result":status,"reason":reason,
                "orders_submitted":receipt.get("orders_submitted") is True,
                "protected":receipt.get("protection_verified") is True}
    except Exception:
        set_attempt_status(root,attempt_id,"unverified_execution_error")
        try:
            os.close(os.open(root/"btc-auto-demo-halt",
                             os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600))
        except OSError:
            pass
        return {"status":"halted_pending_operator_review",
                "reason":"unverified_execution_error"}


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",default="data")
    parser.add_argument("--check-only",action="store_true")
    parser.add_argument("--serve",action="store_true")
    args=parser.parse_args(argv)
    if not args.serve:
        print(json.dumps(run_once(args.data_dir,do_execute=False),sort_keys=True))
        return 0
    while True:
        report=run_once(args.data_dir,do_execute=True)
        # Fixed status fields, no wallet balances, model payloads or secrets.
        print(json.dumps(report,sort_keys=True),flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
