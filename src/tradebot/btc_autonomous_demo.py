"""Bounded BTCUSD Delta India DEMO-only unattended pilot.

Runs read-only eligibility checks every five minutes and may reserve at most
48 GPT-6 FIRE attempts per UTC day, at least five minutes apart.
After a verified trade close, waits five minutes before trying another. Broker risk/protection
checks remain inside SupervisedBTCController. No production host is supported.
"""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from contextlib import closing
from uuid import uuid4
import json
import os
import sqlite3
import stat
import time

from tradebot.delta import DeltaDemo, DEMO_API
from tradebot.autonomous_cooldown import post_close_cooldown
from tradebot.btc_supervised_execution import SupervisedBTCController
from tradebot.btc_supervised_equity_guard import SupervisedSessionEquityGuard
from tradebot.fire_btc_supervised_commission import readonly_btc_commission_preflight
from tradebot.fire_account_guard import (
    AccountExposureRejected, require_flat_demo_account_for_configuration,
)
from tradebot.btc_demo_size import MAX_AUTONOMOUS_LARGE_CONTRACTS
from tradebot.fire_risk import FireRiskLimits, assess_fire_plan
from tradebot.signed_margin_mode import signed_account_margin_mode
from tradebot.fire_account_guard import require_flat_demo_account
from tradebot.btc_supervised_recent24h import load_recent24h_strategy_context

# Historical arm token deliberately stays unchanged: rotating this secret
# would unexpectedly disarm an already-approved isolated DEMO worker.
ARM_CONTENT = "DELTA-INDIA-DEMO:BTCUSD:UNATTENDED:30MIN-MAX48-DYNAMIC6"
MAX_DAILY_ATTEMPTS = 48
MIN_INTERVAL = 5 * 60
POLL_SECONDS = 300
TERMINAL_SAFE = {"rejected_no_order", "flat_verified"}


def arm_path():
    # Broker-account migration must never reuse the old main-account arm.
    label = os.environ.get("TRADEBOT_EXPECTED_DEMO_SUBACCOUNT")
    name = ("btc-isolated-autonomous-armed" if label == "BTC"
            else "btc-auto-demo-armed")
    return Path.home() / ".config" / "tradebot2" / name


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


# No UTC-day or per-trade estimated-loss percentage halt on autonomous DEMO.
# Verified chart-based SL/TP, broker margin, position cap, liquidation checks,
# 15-minute session, weekly/peak and protection gates still apply.


def signed_isolated_margin_proven(broker):
    """Verify the same signed margin identity required post-fill.

    A demo owner declaration permits inspection but is not usable to certify
    broker liquidation clearance. Never send another fee-incurring parent
    order when this exact post-fill prerequisite cannot be satisfied.
    """
    try:
        return signed_account_margin_mode(broker) == "isolated"
    except Exception:
        return False


class AutoBTCController(SupervisedBTCController):
    def __init__(self,path,*,enabled=False,**kwargs):
        super().__init__(path,enabled=enabled,**kwargs)
        self.equity_guard = SupervisedSessionEquityGuard(
            self.path.parent/"fire-equity-risk.sqlite",
            allow_daily_loss_warning=True,
            allow_portfolio_loss_warnings=True,
            allow_initial_isolated_genesis=True)

    def _require_account_flat(self, exchange, product_id):
        if not is_armed():
            raise ValueError("autonomous_demo_disarmed")
        # The autonomous worker is scoped to the explicitly named isolated
        # BTC child. The inherited supervised path uses the old MAIN-account
        # owner declaration, which must never authorize this child.
        if os.environ.get("TRADEBOT_EXPECTED_DEMO_SUBACCOUNT") != "BTC":
            raise ValueError("autonomous_btc_isolated_scope_required")
        if not signed_isolated_margin_proven(exchange):
            raise ValueError("signed_demo_margin_mode_required_before_entry")
        # Live full-account exposure is reverified before the model call and
        # the POST, against the SAME subaccount credentials.
        return require_flat_demo_account(
            exchange, selected_symbol=self.symbol,
            selected_product_id=product_id)

    def _decision_context(self, exchange, collected, midpoint):
        # Public BTC candles are account-independent; the archival DB stays
        # shared under the original data root while trades, equity and FIRE
        # receipts are kept strictly inside the isolated account directory.
        if self.path.parent.name != "btc-isolated":
            raise ValueError("autonomous_btc_private_data_scope_required")
        if self.path.parent.is_symlink() or self.path.parent.parent.is_symlink():
            raise ValueError("untrusted_btc_market_archive_root")
        context, levels = load_recent24h_strategy_context(
            self.path.parent.parent, at=collected, price=midpoint)
        self._restricted_levels = levels
        self._restricted_at = int(collected.timestamp()) // 300 * 300
        return context

    def _allow_wait_choice(self):
        """Autonomous AI may propose only LONG/SHORT, not a neutral choice."""
        return False

    def _hard_contract_cap(self):
        """AI chooses quantity; separate absolute DEMO safety cap remains six."""
        return MAX_AUTONOMOUS_LARGE_CONTRACTS

    def _max_contracts_for_entry(self, budget):
        return min(MAX_AUTONOMOUS_LARGE_CONTRACTS, super()._max_contracts_for_entry(budget))

    def _model_entry_budget(self, exchange, product_id, price):
        """Read-only maximum-affordability preview, NOT broker leverage proof.

        GPT-6 must choose its own leverage. Its suggested quantity is then
        checked again at that exact leverage, against signed wallet equity
        and the existing 20%-of-equity margin share before any order.
        """
        preview = self._entry_budget(
            exchange, product_id, price, planned_leverage=20)
        return {
            **preview,
            "capacity_preview_only": True,
            "capacity_preview_leverage": 20,
            "chosen_leverage_requires_live_broker_recheck": True,
        }

    def _normalize_plan(self, plan, context):
        """Preserve the AI-selected quantity: no evidence-tier downgrading.

        A malformed or unaffordable proposal is rejected by later independently
        signed broker and risk checks; never silently turn it into another order.
        Existing absolute demo cap remains a separate execution safety bound.
        """
        self._sizing_record = {}
        proposed = plan.get("contracts")
        if type(proposed) is not int or not 1 <= proposed <= self._hard_contract_cap():
            return plan
        self._sizing_record = {
            "policy": "btc-demo-model-selected-size-v1",
            "model_proposed_contracts": proposed,
            "selected_contracts": proposed,
            "model_selected_leverage": plan.get("leverage"),
            "quantity_auto_reduced": False,
        }
        return plan

    def _entry_sizing_record(self):
        return {"sizing_evidence": self._sizing_record} if getattr(
            self, "_sizing_record", None) else {}

    def _assess_risk(self, plan, budget, quote):
        """Accept chart-chosen GPT-6 SL/TP without any fixed equity-loss ceiling.

        Still calculate and record estimated loss (fees/slippage included).
        Position size, broker affordability, liquidation cushion, effective
        leverage and reward/risk continue to be independently enforced.
        """
        size = plan.get("contracts")
        if type(size) is not int or not 1 <= size <= self._hard_contract_cap():
            from tradebot.fire_risk import RiskRejected
            raise RiskRejected("Unsupported autonomous BTC demo size")
        return assess_fire_plan(
            plan, budget, quote, limits=FireRiskLimits(
                max_contracts=self._hard_contract_cap(),
                equity_risk_fraction=None,
                minimum_net_reward_risk=None,
                minimum_gross_reward_risk=Decimal("1"),
                version="btc-demo-chart-stop-v4"))

    def _additional_fire_scope(self):
        return {
            "strategy_history_version": "btc-demo-recent24h-v1",
            "unattended_demo_mode": True,
            "max_contracts_per_entry": MAX_AUTONOMOUS_LARGE_CONTRACTS,
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
                    preflight=readonly_btc_commission_preflight,
                    margin_proof=signed_isolated_margin_proven):
    """Fresh authenticated read-only gate; no order authority by itself."""
    # DeltaDemo does not read credentials from environment by itself.
    # Supply them only to the readonly instance (never stored or reported).
    broker = broker_factory(
        api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
        api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
        allow_orders=False)
    if getattr(broker, "base_url", None) != DEMO_API or broker.allow_orders is not False:
        return False
    r = preflight(
        broker, Path(data_dir), allow_daily_loss_warning=True,
        allow_portfolio_loss_warnings=True, allow_signed_subaccount=True)
    return (
        type(r) is dict
        and r.get("status") == "operator_review_candidate_only"
        and r.get("blockers") == []
        and r.get("supervised_session_verified") is True
        and r.get("recent_btc_history_local_quality_verified") is True
        and r.get("signed_isolated_margin_verified") is True
        and r.get("margin_evidence_source") == "signed_parent_subaccount"
        and r.get("owner_declared_main_isolated_accepted") is False
        and r.get("account_wide_flatness_verified") is True
        and r.get("watchdog_and_collector_active") is True
        and r.get("both_dashboard_fire_endpoints_disabled") is True
        and r.get("trade_authorized") is False
        and margin_proof(broker) is True
    )


def signed_active_trade_skip(root, *, broker_factory=DeltaDemo,
                             exposure_check=require_flat_demo_account_for_configuration):
    """Return True only for a confirmed signed non-flat account, not a read error.

    A broker outage, malformed pagination or missing credential is UNKNOWN and
    must not be reported as an open trade. No broker mutation is permitted.
    """
    try:
        broker = broker_factory(
            api_key=os.getenv("DELTA_DEMO_API_KEY", ""),
            api_secret=os.getenv("DELTA_DEMO_API_SECRET", ""),
            allow_orders=False)
        if (getattr(broker, "base_url", None) != DEMO_API
                or getattr(broker, "allow_orders", None) is not False):
            return None
        exposure_check(broker)
        return False
    except AccountExposureRejected as exc:
        return True if str(exc) in {
            "Account has open exposure",
            "Account has pending orders",
            "FIRE market has open exposure",
        } else None
    except Exception:
        return None


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
                if detail.get("reason_code")=="gpt6_wait_no_trade":
                    return True
                # Only precisely reviewed historical no-order incidents
                # qualify. An old generic risk_governor_failed must reproduce
                # the net reward/risk deficiency from immutable input+receipt;
                # the signed incident review enforces this additional evidence.
                # Never rewrite the FIRE history or guess at another failure.
                if (detail.get("reason_code") in (
                        "model_decision_failed", "risk_governor_failed")
                        and detail.get("orders_submitted") is False):
                    from tradebot.btc_auto_review import reviewed_receipt_matches
                    return reviewed_receipt_matches(root)
                return False
            return (last[0]=="flat_verified"
                    and detail.get("reason_code") not in (
                        "emergency_flat_verified","execution_or_protection_unverified"))
    except (sqlite3.Error,OSError,ValueError,TypeError):
        return False


def run_once(data_dir, *, instant=None, armed=is_armed,
             candidate=check_candidate, controller_factory=AutoBTCController,
             receipts_safe=prior_fire_receipts_safe,
             active_trade_probe=signed_active_trade_skip,
             cooldown_check=post_close_cooldown, do_execute=False):
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
        # Do not spend GPT tokens or reserve an attempt when signed broker
        # evidence specifically identifies a running position/order.
        try:
            active = active_trade_probe(root)
        except Exception:
            active = None
        if active is True:
            return {"status":"skipped_active_trade"}
        return {"status":"read_only_preflight_unavailable"}
    if not receipts_safe(root):
        return {"status":"previous_fire_decision_or_execution_unresolved"}
    if not do_execute:
        return {"status":"eligible_read_only_no_order"}
    cooldown, remaining = cooldown_check(
        root, fire_filename="fire-ops.sqlite", now=now)
    if cooldown == "unavailable":
        return {"status":"verified_trade_close_time_unavailable"}
    if cooldown == "cooling_down":
        return {"status":"post_trade_cooldown",
                "remaining_seconds":remaining}
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
