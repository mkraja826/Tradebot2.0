"""Offline verification of isolated one-shot BTC supervised DEMO FIRE.

No network, broker POST, paid model call, real service or original ledger.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from equity_fixtures import receipt_for
from tradebot.delta import DEMO_API
from tradebot.btc_supervised_equity_guard import SupervisedSessionEquityGuard
from tradebot.btc_supervised_execution import SupervisedBTCController, STRATEGY_VERSION
from tradebot.fire_execution import FireDemoController, FireTradeError
from tradebot.fire_probe import instruction_for_snapshot, INSTRUCTION, PlanError
from tradebot.fire_btc_supervised_commission import (
    run_operator_btc_commission, readonly_btc_commission_preflight,
    ATTEMPT_FILE, APPROVAL_PHRASE,
)
from tradebot.portfolio_equity_guard import EquityRiskError

NOW = datetime(2026, 11, 22, 17, 30, tzinfo=timezone.utc)


def health(*, daily="verified", watchdog="healthy", conditions=None):
    return {
        "database_integrity": "verified",
        "daily_checkpoint": daily,
        "latest_receipt_status": "verified", "observation_status": "fresh",
        "blocking_conditions": (
            ["weekly_checkpoint_missed_window"] if conditions is None
            else conditions),
        "monitoring": {
            "watchdog": watchdog, "equity_collector": "healthy",
            "alert_codes": [] if watchdog == "healthy" else ["watchdog_failed"],
            "watchdog_age_seconds": 3, "equity_collector_age_seconds": 10,
        },
    }


def recent_features():
    return {
        "as_of": int(NOW.timestamp())//300*300,
        "ema_15m": {"ema20": 100, "slope": "flat", "close": 100},
        "ema_1h": {"ema20": 100, "slope": "flat", "close": 100},
        "atr_5m": 1.3, "session_vwap": 100,
        "since_exit": None,
    }


def recent_levels():
    return {
        "source": "original_delta_demo_24h_5m_local_only",
        "strategy_history_version": STRATEGY_VERSION,
        "as_of": int(NOW.timestamp())//300*300,
        "resolution": "5m", "timezone": "UTC",
        "independent_price_validation": False,
        "periods": {"last_24h": {
            "high": 102, "low": 98, "bars": 288,
            "expected": 288, "quality_status": "provisionally_valid"}},
    }


class SessionGuardTests(unittest.TestCase):
    def fresh(self, *, status=None, watermark="100"):
        return SupervisedSessionEquityGuard(
            "/unused/signed-original.sqlite",
            health_fn=lambda path, at: health() if status is None else status,
            peak_reader=lambda path: (Decimal(watermark), (200, 500)),
        )

    def test_original_missed_week_is_allowed_for_new_short_session_only(self):
        guard = self.fresh()
        r = guard.require_verified_read(
            "100", receipt_for("100", NOW), now=NOW)
        self.assertTrue(r["approved"])
        self.assertFalse(r["normal_weekly_checkpoint_overridden"])
        self.assertTrue(guard.require_verified_read(
            "99.8", receipt_for("99.8", NOW + timedelta(seconds=60)),
            now=NOW + timedelta(seconds=60))["approved"])

    def test_recheck_rejects_0_5_percent_loss_and_stale_session(self):
        guard = self.fresh()
        guard.require_verified_read("100", receipt_for("100", NOW), now=NOW)
        with self.assertRaises(EquityRiskError):
            guard.require_verified_read(
                "99.4", receipt_for("99.4",NOW+timedelta(seconds=60)),
                now=NOW+timedelta(seconds=60))
        with self.assertRaises(EquityRiskError):
            guard.require_verified_read(
                "100",receipt_for("100",NOW+timedelta(minutes=16)),
                now=NOW+timedelta(minutes=16))

    def test_invalid_health_and_mismatched_original_ledger_block(self):
        for status in (health(daily="missed_window"),
                       health(watchdog="down"),
                       health(conditions=["equity_database_corrupt"])):
            with self.subTest(status=status["blocking_conditions"]):
                guard = self.fresh(status=status)
                with self.assertRaises(EquityRiskError):
                    guard.require_verified_read(
                        "100",receipt_for("100",NOW),now=NOW)
        guard = self.fresh()
        guard.require_verified_read("100",receipt_for("100",NOW),now=NOW)
        guard.peak_reader=lambda p: (Decimal("100"),(200,501))
        with self.assertRaises(EquityRiskError):
            guard.require_verified_read(
                "100",receipt_for("100",NOW+timedelta(seconds=10)),
                now=NOW+timedelta(seconds=10))


class ControllerSafetyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_pilot_controller_is_off_by_default_and_locked_to_btc(self):
        ctrl = SupervisedBTCController(self.root/"fire-ops.sqlite")
        self.assertFalse(ctrl.enabled)
        self.assertEqual(ctrl.start(), (False,"execution_disabled"))
        self.assertIsInstance(ctrl.equity_guard,SupervisedSessionEquityGuard)
        with self.assertRaises(ValueError):
            SupervisedBTCController(self.root/"fire2.sqlite",symbol="XAUTUSD")

    def test_pilot_history_contains_no_fabricated_monthly_levels(self):
        ctrl=SupervisedBTCController(self.root/"fire-ops.sqlite")
        with patch(
            "tradebot.btc_supervised_execution.load_recent24h_strategy_context",
            return_value=(recent_features(),recent_levels())
        ):
            ctx=ctrl._decision_context(None,NOW,100)
        self.assertEqual(ctx,recent_features())
        levels=ctrl._historical_levels(NOW,100)
        self.assertEqual(set(levels["periods"]),{"last_24h"})
        self.assertEqual(ctrl._additional_fire_scope()["strategy_history_version"],
                         STRATEGY_VERSION)
        payload = {
            "environment":"delta-india-demo",
            "core":{"ticker":{"symbol":"BTCUSD",
                               "mark_price":"100.01"},
                    "best_bid":"100","best_ask":"100.02"},
            "fire_execution_scope":{
                "strategy_history_version":STRATEGY_VERSION,
                "max_contracts_per_entry":1,
                "attached_stop_loss_and_take_profit_required":True,
            },
            "indicators":{**ctx,"historical_levels":levels,
                "local_market_screen":ctrl._pre_model_market_screen(
                    {"core":{"ticker":{"symbol":"BTCUSD","mark_price":"100.01"},
                             "best_bid":"100","best_ask":"100.02"}},ctx)},
        }
        prompt=instruction_for_snapshot(payload)
        self.assertNotEqual(prompt,INSTRUCTION)
        self.assertNotIn("month highs",prompt)
        self.assertIn("last 24 hours",prompt)
        payload["indicators"]["historical_levels"]["periods"]["month"] = {
            "quality_status":"provisionally_valid"}
        with self.assertRaises(PlanError):
            instruction_for_snapshot(payload)

    def test_regular_fire_still_checks_all_six_periods(self):
        class FakeArchive:
            def levels(self,*args):
                return {"periods":{
                    k: {"quality_status": "provisionally_valid"}
                    for k in ("day", "previous_day", "week",
                              "previous_week", "month", "previous_month")}}
        normal=FireDemoController(self.root/"normal.sqlite")
        normal.archive=FakeArchive()
        self.assertEqual(
            len(normal._historical_levels(NOW,100)["periods"]),6)
        self.assertEqual(normal._additional_fire_scope(),{})
        normal.archive.levels=lambda *args: {"periods":{
            "last_24h":{"quality_status":"provisionally_valid"}}}
        with self.assertRaises(FireTradeError):
            normal._historical_levels(NOW,100)
        pilot=SupervisedBTCController(self.root/"pilot.sqlite")
        with self.assertRaises(FireTradeError):
            pilot._historical_levels(NOW,100)


class FakeReadOnlyBroker:
    base_url=DEMO_API
    allow_orders=False
    def __init__(self,**kwargs):
        self.kwargs=kwargs


class CommissionSafetyTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)

    @staticmethod
    def allowed():
        return {
            "status":"operator_review_candidate_only", "blockers":[],
            "supervised_session_verified":True,
            "recent_btc_history_local_quality_verified":True,
            "signed_isolated_margin_verified":True,
            "account_wide_flatness_verified":True,
            "watchdog_and_collector_active":True,
            "both_dashboard_fire_endpoints_disabled":True,
            "trade_authorized":False,
        }

    def test_readonly_never_consumes_one_attempt(self):
        q=run_operator_btc_commission(
            self.root,broker_factory=FakeReadOnlyBroker,
            readiness=lambda broker,root:self.allowed())
        self.assertTrue(q["can_request_operator_approval"])
        self.assertFalse((self.root/ATTEMPT_FILE).exists())
        self.assertFalse(q["order_submitted"])

    def test_failed_margin_cannot_create_attempt_or_invoke_controller(self):
        q=self.allowed()
        q["signed_isolated_margin_verified"]=False
        q["status"]="blocked"
        q["blockers"]=["signed_current_demo_isolated_margin_unverified"]
        with self.assertRaises(ValueError):
            run_operator_btc_commission(
                self.root,execute=True,approval=APPROVAL_PHRASE,
                broker_factory=FakeReadOnlyBroker,
                readiness=lambda *args:q,
                controller_factory=lambda *args,**kwargs:
                    self.fail("controller must never be constructed"))
        self.assertFalse((self.root/ATTEMPT_FILE).exists())

    def test_explicit_approval_and_consumed_lock_before_controller(self):
        class Controller:
            def __init__(inner,path,**kwargs):
                assert (self.root/ATTEMPT_FILE).is_file()
                assert path.name=="fire-ops.sqlite"
                assert kwargs["enabled"] is True
            def start(inner):
                return True,"accepted"
            def snapshot(inner):
                return {"status":"rejected_no_order",
                        "orders_submitted":False,
                        "protection_verified":False}
        kwargs=dict(
            broker_factory=FakeReadOnlyBroker,
            readiness=lambda *args:self.allowed(),
            controller_factory=Controller)
        with self.assertRaises(ValueError):
            run_operator_btc_commission(
                self.root,execute=True,approval="incorrect",**kwargs)
        self.assertFalse((self.root/ATTEMPT_FILE).exists())
        result=run_operator_btc_commission(
            self.root,execute=True,approval=APPROVAL_PHRASE,**kwargs)
        self.assertTrue(result["request_accepted"])
        self.assertTrue(result["one_shot_consumed"])
        self.assertFalse(result["order_submitted"])
        with self.assertRaises(ValueError):
            run_operator_btc_commission(
                self.root,execute=True,approval=APPROVAL_PHRASE,**kwargs)

    def test_readonly_gate_reports_every_unmet_requirement(self):
        class Broker: base_url=DEMO_API; allow_orders=False
        report=readonly_btc_commission_preflight(
            Broker(),self.root,
            services=lambda:True,dashboard_disabled=lambda:True,
            session_fn=lambda *a:{"status":"baseline_candidate_review_only",
                                  "session_budget_within_limits":True,
                                  "trade_authorized":False},
            recent_fn=lambda *a:{
                "status":"recent24h_local_candidate_only",
                "complete_contiguous_24h":True,
                "retained_bars":288,"quarantined_bars":0,
                "suspect_bars":0,"trade_authorized":False},
            margin_fn=lambda *a: (_ for _ in ()).throw(ValueError("missing")),
            flat_fn=lambda *a:self.fail("cannot call without signed margin"))
        self.assertEqual(report["blockers"],
                         ["signed_current_demo_isolated_margin_unverified"])
        self.assertFalse(report["trade_authorized"])


if __name__=="__main__":
    unittest.main()
