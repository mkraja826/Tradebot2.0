"""Independent DeepSeek XAUTUSD unattended Delta India DEMO worker.

Checks eligibility every 5m with no daily attempt-count cap,
and waits at least five minutes after verified trade close before a new entry.
Skips signed live exposure; never replays unresolved broker orders.
Order authority belongs solely to the protected Gold FIRE controller.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json
import os
import sqlite3
import stat
import time

from tradebot.gold_autonomous_controller import AutoGoldController
from tradebot.autonomous_cooldown import post_close_cooldown
from tradebot.fire_account_guard import AccountExposureRejected
from tradebot.btc_autonomous_demo import signed_active_trade_skip
from tradebot.gold_autonomous_readiness import gold_preflight

# Historical arm token deliberately stays unchanged: rotating this secret
# would unexpectedly disarm an already-approved isolated DEMO worker.
ARM_CONTENT = "DELTA-INDIA-DEMO:XAUTUSD:DEEPSEEK:UNATTENDED:30MIN-MAX48-DYNAMIC6"
MIN_INTERVAL=5*60
POLL_SECONDS=300
TERMINAL_SAFE={"rejected_no_order","flat_verified"}
SAFE_NO_ORDER_REASONS = frozenset((
    "risk_governor_failed", "autonomous_invalid_wait",
    "market_quality_failed", "provider_network_error"))


def _no_durable_intent(root, press):
    """A retryable AI-provider failure must predate any durable broker POST."""
    file = Path(root)/"fire-xaut.sqlite"
    if type(press) is not str or not press or file.is_symlink() or not file.is_file():
        return False
    try:
        with closing(sqlite3.connect(
                file.absolute().as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                              "AND name='fire_entries'").fetchone():
                return False
            return db.execute("SELECT 1 FROM fire_entries WHERE press=? LIMIT 1",
                              (press,)).fetchone() is None
    except (sqlite3.Error, ValueError, OSError, TypeError):
        return False



def gold_arm_path():
    return Path.home()/".config"/"tradebot2"/"gold-isolated-autonomous-armed"


def is_gold_armed(path=None):
    path=Path(path) if path is not None else gold_arm_path()
    try:
        if not path.is_file() or path.is_symlink():
            return False
        fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
        try:
            m=os.fstat(fd)
            if (not stat.S_ISREG(m.st_mode)
                    or stat.S_IMODE(m.st_mode)!=0o600
                    or m.st_uid!=os.geteuid() or m.st_size>100):
                return False
            data=os.read(fd,101)
        finally:
            os.close(fd)
        return data==(ARM_CONTENT+"\n").encode()
    except OSError:
        return False


def _connect(root):
    db=sqlite3.connect(Path(root)/"gold-auto-demo.sqlite",timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("""CREATE TABLE IF NOT EXISTS gold_auto_attempts(
        attempt_id TEXT PRIMARY KEY, utc_day TEXT NOT NULL,
        requested_at INTEGER NOT NULL, status TEXT NOT NULL)""")
    return db


def claim_attempt(root, instant):
    ts=int(instant.timestamp())
    day=instant.date().isoformat()
    with closing(_connect(root)) as db:
        db.execute("BEGIN IMMEDIATE")
        last=db.execute("SELECT requested_at FROM gold_auto_attempts "
                        "ORDER BY requested_at DESC LIMIT 1").fetchone()
        # UTC-day is retained only for historical audit/reporting, not
        # as a quota. No daily AI attempt-count allocation remains.
        if last and ts-last[0]<MIN_INTERVAL:
            db.rollback()
            return None
        attempt=uuid4().hex
        db.execute("INSERT INTO gold_auto_attempts VALUES (?,?,?,?)",
                   (attempt,day,ts,"reserved_before_model"))
        db.commit()
        return attempt


def set_attempt_status(root,attempt,status):
    with closing(_connect(root)) as db:
        db.execute("UPDATE gold_auto_attempts SET status=? WHERE attempt_id=?",
                   (status,attempt))
        db.commit()


def receipts_safe(root):
    path=Path(root)/"fire-xaut.sqlite"
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with closing(sqlite3.connect(
            path.absolute().as_uri()+"?mode=ro",uri=True,timeout=3)) as db:
            db.execute("PRAGMA query_only=ON")
            values=db.execute(
                "SELECT DISTINCT status FROM fire_requests").fetchall()
            if any(v[0] not in TERMINAL_SAFE for v in values):
                return False
            row=db.execute("SELECT press,status,result FROM fire_requests "
                "ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
            if row is None:return True
            detail=json.loads(row[2])
            if not isinstance(detail,dict):return False
            if row[1]=="rejected_no_order":
                # A *documented* no-order rejection may be revisited on the
                # next normal interval, after a fresh broker-wide flatness
                # check. It is never treated as evidence of a protected fill.
                # Unknown/ambiguous outcomes remain blocked.
                return (detail.get("orders_submitted") is False
                    and detail.get("protection_verified") is False
                    and detail.get("reason_code") in SAFE_NO_ORDER_REASONS
                    and (detail.get("reason_code") != "provider_network_error"
                         or _no_durable_intent(root,row[0])))
            # Broker-signed watchdog closed an ordinarily protected trade.
            # In a naturally flat terminal receipt, attached protection is
            # no longer active, so do not require protection_verified=True.
            return (row[1]=="flat_verified"
                and detail.get("reason_code") not in (
                    "emergency_flat_verified",
                    "execution_or_protection_unverified"))
    except (sqlite3.Error,OSError,ValueError,TypeError):
        return False


def check_candidate(root,*,preflight=gold_preflight):
    evidence=preflight(root)
    return (type(evidence) is dict
        and evidence.get("status")=="eligible_read_only_no_order"
        and evidence.get("blockers")==[]
        and evidence.get("symbol")=="XAUTUSD"
        and evidence.get("model")=="tb-deepseek-v4-1-flash"
        and evidence.get("signed_isolated_margin") is True
        and evidence.get("account_flat") is True
        and evidence.get("recent_24h_complete") is True
        and evidence.get("fresh_equity") is True
        and evidence.get("services_healthy") is True
        and evidence.get("dashboard_fire_disabled") is True
        and evidence.get("order_authorized") is False)


def _mark_halt(root):
    path=Path(root)/"gold-auto-demo-halt"
    try:
        os.close(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600))
    except FileExistsError:
        pass


def run_once(data_dir,*,instant=None,armed=is_gold_armed,candidate=check_candidate,
             active_trade_probe=signed_active_trade_skip,
             controller_factory=AutoGoldController,receipt_check=receipts_safe,
             cooldown_check=post_close_cooldown, do_execute=False):
    now=instant or datetime.now(timezone.utc)
    root=Path(data_dir)
    if (not root.is_dir() or root.is_symlink() or root.name!="gold-isolated"
            or now.tzinfo is None or now.utcoffset() is None):
        return {"status":"blocked","reason":"gold_isolated_root_or_clock_invalid"}
    if not armed():
        return {"status":"disarmed"}
    if (root/"gold-auto-demo-halt").exists():
        return {"status":"halted_pending_operator_review"}
    try:
        eligible=candidate(root)
    except Exception:
        eligible=False
    if not eligible:
        try:
            active=active_trade_probe(root)
        except Exception:
            active=None
        if active is True:
            return {"status":"skipped_active_trade"}
        return {"status":"read_only_preflight_unavailable"}
    if not receipt_check(root):
        return {"status":"previous_gold_fire_unresolved"}
    if not do_execute:
        return {"status":"eligible_read_only_no_order"}
    cooldown, remaining = cooldown_check(
        root, fire_filename="fire-xaut.sqlite", now=now)
    if cooldown == "unavailable":
        return {"status":"verified_trade_close_time_unavailable"}
    if cooldown == "cooling_down":
        return {"status":"post_trade_cooldown",
                "remaining_seconds":remaining}
    attempt=claim_attempt(root,now)
    if attempt is None:
        return {"status":"interval_cooldown_active"}
    try:
        bot=controller_factory(root/"fire-xaut.sqlite",enabled=True,
                               spawn=lambda task:task())
        accepted,reason=bot.start(press=attempt)
        receipt=bot.snapshot()
        status=receipt.get("status") if accepted else "start_rejected"
        set_attempt_status(root,attempt,status)
        protected=(status=="protected_active"
            and receipt.get("protection_verified") is True
            and receipt.get("liquidation_verified") is True)
        emergency=(status=="flat_verified"
            and receipt.get("reason_code") in (
                "emergency_flat_verified","execution_or_protection_unverified"))
        # No-order discretionary risk/model failures are not broker
        # exposure incidents. Log them as rejected attempts, do not halt
        # unattended demo scheduling solely for a documented no-order.
        safe_no_order = (
            status == "rejected_no_order"
            and receipt.get("orders_submitted") is False
            and receipt.get("protection_verified") is False
            and receipt.get("reason_code") in SAFE_NO_ORDER_REASONS
            and (receipt.get("reason_code") != "provider_network_error"
                 or _no_durable_intent(root,attempt)))
        if ((status not in TERMINAL_SAFE and not protected)
                or (status=="rejected_no_order" and not safe_no_order)
                or emergency):
            _mark_halt(root)
        return {
            "status":"attempt_finished","accepted":bool(accepted),
            "result":status,"reason":reason,
            "orders_submitted":receipt.get("orders_submitted") is True,
            "protected":receipt.get("protection_verified") is True,
        }
    except Exception:
        set_attempt_status(root,attempt,"unverified_execution_error")
        _mark_halt(root)
        return {"status":"execution_unknown_halted"}


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",default="data/gold-isolated")
    parser.add_argument("--serve",action="store_true")
    args=parser.parse_args(argv)
    if not args.serve:
        print(json.dumps(run_once(args.data_dir,do_execute=False),
                         sort_keys=True))
        return 0
    while True:
        report=run_once(args.data_dir,do_execute=True)
        print(json.dumps(report,sort_keys=True),flush=True)
        time.sleep(POLL_SECONDS)


if __name__=="__main__":
    raise SystemExit(main())
