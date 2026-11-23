"""Offline tests: autonomous DEMO BTC never escapes bounded gates."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import sqlite3
from tradebot.btc_autonomous_demo import is_armed,ARM_CONTENT,run_once,claim_attempt

NOW=datetime(2026,11,23,1,tzinfo=timezone.utc)

class AutoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def fake(self, reason="gpt6_wait_no_trade"):
        class Controller:
            starts=0
            def __init__(inner,*args,**kwargs):
                assert kwargs["enabled"] is True
            def start(inner,**kwargs):
                Controller.starts+=1
                return True,"accepted"
            def snapshot(inner):
                return {"status":"rejected_no_order","reason_code":reason,
                        "orders_submitted":False,"protection_verified":False}
        return Controller

    def test_disarmed_never_calls_candidate(self):
        value=run_once(self.root,instant=NOW,armed=lambda:False,
                       candidate=lambda x:self.fail("candidate called"),
                       do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0))
        self.assertEqual(value["status"],"disarmed")

    def test_arming_private_and_exact(self):
        path=self.root/"arm"
        self.assertFalse(is_armed(path))
        path.write_text(ARM_CONTENT+"\n")
        path.chmod(0o644)
        self.assertFalse(is_armed(path))
        path.chmod(0o600)
        self.assertTrue(is_armed(path))
        path.write_text("delta-live")
        self.assertFalse(is_armed(path))

    def test_main_arm_never_authorizes_isolated_btc(self):
        from unittest.mock import patch
        from tradebot.btc_autonomous_demo import arm_path
        with patch.dict("os.environ", {}, clear=False):
            with patch.dict("os.environ",
                            {"TRADEBOT_EXPECTED_DEMO_SUBACCOUNT": "BTC"}):
                self.assertEqual(arm_path().name,
                                 "btc-isolated-autonomous-armed")
            with patch.dict("os.environ",
                            {"TRADEBOT_EXPECTED_DEMO_SUBACCOUNT": "GOLD"}):
                self.assertEqual(arm_path().name, "btc-auto-demo-armed")

    def test_isolated_account_uses_signed_flatness_not_main_owner_attestation(self):
        from unittest.mock import patch
        from tradebot.btc_autonomous_demo import AutoBTCController
        b = AutoBTCController(self.root / "fire-ops.sqlite")
        with patch("tradebot.btc_autonomous_demo.is_armed",
                   return_value=True):
            with patch("tradebot.btc_autonomous_demo.signed_isolated_margin_proven",
                       return_value=True):
                with patch("tradebot.btc_autonomous_demo.require_flat_demo_account",
                           return_value={"account_flat_verified": True}) as signed:
                    with patch.dict("os.environ",
                                    {"TRADEBOT_EXPECTED_DEMO_SUBACCOUNT": "BTC"}):
                        with patch("tradebot.btc_autonomous_demo.require_entry_cooldown") as cooldown:
                            result = b._require_account_flat(object(), 84)
                            cooldown.assert_called_once_with(
                                self.root, fire_filename="fire-ops.sqlite")
                    self.assertTrue(result["account_flat_verified"])
                    self.assertEqual(signed.call_args.kwargs["selected_symbol"], "BTCUSD")
                    self.assertEqual(signed.call_args.kwargs["selected_product_id"], 84)
                    with patch.dict("os.environ",
                                    {"TRADEBOT_EXPECTED_DEMO_SUBACCOUNT": "GOLD"}):
                        with self.assertRaisesRegex(ValueError, "isolated_scope_required"):
                            b._require_account_flat(object(), 84)

    def test_isolated_btc_candles_are_shared_not_equity_receipts(self):
        from unittest.mock import patch
        from tradebot.btc_autonomous_demo import AutoBTCController
        private = self.root / "btc-isolated"
        private.mkdir()
        b = AutoBTCController(private / "fire-ops.sqlite")
        context = {"technical_5m": {"ema": 1}}
        levels = {"as_of": 42}
        with patch("tradebot.btc_autonomous_demo.load_recent24h_strategy_context",
                   return_value=(context, levels)) as loader:
            self.assertEqual(
                b._decision_context(object(), NOW, 61_000),
                context)
        self.assertEqual(loader.call_args.args[0], self.root)
        self.assertEqual(b._restricted_levels, levels)
        with patch("tradebot.btc_autonomous_demo.load_recent24h_strategy_context") as loader:
            another = AutoBTCController(self.root / "fire-ops.sqlite")
            with self.assertRaisesRegex(ValueError, "private_data_scope_required"):
                another._decision_context(object(), NOW, 61_000)
            loader.assert_not_called()

    def test_no_daily_count_cap_and_five_minute_spacing(self):
        start=NOW.replace(hour=0)
        for i in range(100):
            when=start+timedelta(minutes=5*i)
            self.assertIsNotNone(claim_attempt(self.root,when))
            # Four minutes after any admitted attempt remains blocked,
            # including after the old quota of 48 is exceeded.
            self.assertIsNone(claim_attempt(self.root,when+timedelta(minutes=4)))
        with sqlite3.connect(self.root/"btc-auto-demo.sqlite") as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM btc_auto_attempts WHERE utc_day=?",
                (start.date().isoformat(),)).fetchone()[0],100)
        self.assertIsNotNone(claim_attempt(self.root,start+timedelta(days=1)))

    def test_dry_run_makes_no_reservation(self):
        value=run_once(self.root,instant=NOW,armed=lambda:True,
                       candidate=lambda x:True,receipts_safe=lambda x:True,do_execute=False)
        self.assertEqual(value["status"],"eligible_read_only_no_order")
        self.assertIsNotNone(claim_attempt(self.root,NOW))

    def test_missing_signed_preflight_makes_no_reservation(self):
        value=run_once(self.root,instant=NOW,armed=lambda:True,
                       candidate=lambda x:False,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0),
                       controller_factory=self.fake())
        self.assertEqual(value["status"],"read_only_preflight_unavailable")
        self.assertIsNotNone(claim_attempt(self.root,NOW))

    def test_model_failure_halts_automatic_retries(self):
        runner=self.fake("model_decision_failed")
        first=run_once(self.root,instant=NOW,armed=lambda:True,
                       candidate=lambda x:True,receipts_safe=lambda x:True,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0),
                       controller_factory=runner)
        self.assertEqual(first["result"],"rejected_no_order")
        self.assertTrue((self.root/"btc-auto-demo-halt").exists())
        second=run_once(self.root,instant=NOW+timedelta(hours=4),
                        armed=lambda:True,candidate=lambda x:True,receipts_safe=lambda x:True,
                        do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0),controller_factory=runner)
        self.assertEqual(second["status"],"halted_pending_operator_review")
        self.assertEqual(runner.starts,1)

    def test_wait_consumes_slot_then_retries_after_five_minutes(self):
        runner=self.fake()
        for instant in (NOW,NOW+timedelta(minutes=5)):
            result=run_once(self.root,instant=instant,armed=lambda:True,
                            candidate=lambda x:True,receipts_safe=lambda x:True,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0),
                            controller_factory=runner)
            self.assertEqual(result["result"],"rejected_no_order")
            self.assertFalse(result["orders_submitted"])
        skipped=run_once(self.root,instant=NOW+timedelta(minutes=9),
                          armed=lambda:True,candidate=lambda x:True,receipts_safe=lambda x:True,
                          do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0),controller_factory=runner)
        self.assertEqual(skipped["status"],"interval_cooldown_active")
        self.assertEqual(runner.starts,2)

    def test_signed_active_position_skips_without_charging_or_model(self):
        runner=self.fake()
        skipped=run_once(self.root,instant=NOW,armed=lambda:True,
                         candidate=lambda x:False,receipts_safe=lambda x:True,
                         active_trade_probe=lambda x:True,
                         do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0),controller_factory=runner)
        self.assertEqual(skipped["status"],"skipped_active_trade")
        self.assertIsNotNone(claim_attempt(self.root,NOW))
        self.assertEqual(runner.starts,0)

    def test_unsigned_broker_error_not_misreported_as_open_trade(self):
        from tradebot.btc_autonomous_demo import signed_active_trade_skip
        from tradebot.fire_account_guard import AccountExposureRejected
        from tradebot.delta import DEMO_API
        class Client:
            base_url=DEMO_API
            allow_orders=False
        broker=lambda **kwargs:Client()
        def missing(client):
            raise AccountExposureRejected("Account-wide positions unverified")
        def opened(client):
            raise AccountExposureRejected("Account has open exposure")
        self.assertIsNone(signed_active_trade_skip(
            self.root,broker_factory=broker,exposure_check=missing))
        self.assertTrue(signed_active_trade_skip(
            self.root,broker_factory=broker,exposure_check=opened))
        self.assertFalse(signed_active_trade_skip(
            self.root,broker_factory=broker,exposure_check=lambda b:None))

    def test_ambiguous_execution_halts_and_never_retries(self):
        class Uncertain:
            def __init__(inner,*args,**kwargs): pass
            def start(inner,**kwargs): raise RuntimeError("could have filled")
        result=run_once(self.root,instant=NOW,armed=lambda:True,
                        candidate=lambda x:True,receipts_safe=lambda x:True,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0),
                        controller_factory=Uncertain)
        self.assertEqual(result["status"],"halted_pending_operator_review")
        self.assertTrue((self.root/"btc-auto-demo-halt").exists())

    def test_autonomous_does_not_install_daily_loss_limit(self):
        from tradebot.btc_autonomous_demo import AutoBTCController
        from tradebot.btc_supervised_equity_guard import SupervisedSessionEquityGuard
        bot = AutoBTCController(self.root / "fire-ops.sqlite")
        self.assertIs(type(bot.equity_guard), SupervisedSessionEquityGuard)
        self.assertTrue(bot.equity_guard.allow_daily_loss_warning)
        self.assertTrue(bot.equity_guard.allow_portfolio_loss_warnings)
        self.assertFalse((self.root / "btc-auto-demo.sqlite").exists())

    def test_daily_only_collector_warning_does_not_hide_broker_failure(self):
        from tradebot.equity_monitor import (
            DAILY_ONLY_WARNING, demo_monitoring_operational,
        )
        healthy = {
            "watchdog": "healthy", "equity_collector": DAILY_ONLY_WARNING,
            "watchdog_age_seconds": 1, "equity_collector_age_seconds": 1,
            "alert_codes": [DAILY_ONLY_WARNING],
        }
        self.assertTrue(demo_monitoring_operational(
            healthy, allow_daily_loss_warning=True))
        self.assertFalse(demo_monitoring_operational(healthy))
        for extra in ("equity_loss_limit_breached", "watchdog_heartbeat_stale"):
            report = {**healthy, "alert_codes": [DAILY_ONLY_WARNING, extra]}
            self.assertFalse(demo_monitoring_operational(
                report, allow_daily_loss_warning=True))

    def test_disarm_file_symlink_never_arms(self):
        p=self.root/"arm"
        other=self.root/"other"
        other.write_text(ARM_CONTENT+"\n")
        other.chmod(0o600)
        p.symlink_to(other)
        self.assertFalse(is_armed(p))

    def test_bounded_autonomous_six_contract_ceiling_preserves_supervised_one(self):
        from tradebot.btc_autonomous_demo import AutoBTCController
        from tradebot.btc_supervised_execution import SupervisedBTCController
        bot=AutoBTCController(self.root/"fire-ops.sqlite")
        supervised=SupervisedBTCController(self.root/"supervised.sqlite")
        self.assertFalse(bot.enabled)
        self.assertEqual(bot._hard_contract_cap(),6)
        self.assertEqual(supervised._hard_contract_cap(),1)
        self.assertEqual(bot._max_contracts_for_entry(
            {"max_contracts_per_entry":40}),6)
        self.assertEqual(bot._max_contracts_for_entry(
            {"max_contracts_per_entry":0}),0)
        scope=bot._additional_fire_scope()
        self.assertEqual(scope["max_contracts_per_entry"],6)
        self.assertTrue(scope["unattended_demo_mode"])
        self.assertIs(scope["daily_attempt_cap_enabled"],False)
        self.assertNotIn("max_new_order_attempts_per_utc_day",scope)

    def test_missing_broker_signed_margin_blocks_even_healthy_owner_attestation(self):
        from tradebot.btc_autonomous_demo import (
            check_candidate, AutoBTCController,
        )
        from tradebot.delta import DEMO_API
        from unittest.mock import patch

        class ReadOnly:
            base_url = DEMO_API
            allow_orders = False

        ok = {
            "status": "operator_review_candidate_only", "blockers": [],
            "supervised_session_verified": True,
            "recent_btc_history_local_quality_verified": True,
            "signed_isolated_margin_verified": True,
            "margin_evidence_source": "signed_parent_subaccount",
            "owner_declared_main_isolated_accepted": False,
            "account_wide_flatness_verified": True,
            "watchdog_and_collector_active": True,
            "both_dashboard_fire_endpoints_disabled": True,
            "trade_authorized": False,
        }
        self.assertFalse(check_candidate(
            self.root, broker_factory=lambda **kw: ReadOnly(),
            preflight=lambda b, p, **kwargs: ok,
            margin_proof=lambda b: False))
        bot = AutoBTCController(self.root / "fire-ops.sqlite")
        with patch("tradebot.btc_autonomous_demo.is_armed", return_value=True):
            with patch("tradebot.btc_autonomous_demo.signed_isolated_margin_proven", return_value=False):
                with patch.dict("os.environ", {"TRADEBOT_EXPECTED_DEMO_SUBACCOUNT": "BTC"}):
                    with self.assertRaisesRegex(ValueError, "signed_demo_margin_mode_required_before_entry"):
                        bot._require_account_flat(object(), 84)

    def test_client_preflight_rejects_missing_margin_owner_verification(self):
        from tradebot.btc_autonomous_demo import check_candidate
        from tradebot.delta import DEMO_API
        class ReadOnly:
            base_url=DEMO_API
            allow_orders=False
        approved={
            "status":"operator_review_candidate_only",
            "blockers":[],
            "supervised_session_verified":True,
            "recent_btc_history_local_quality_verified":True,
            "signed_isolated_margin_verified": True,
            "margin_evidence_source": "signed_parent_subaccount",
            "owner_declared_main_isolated_accepted": False,
            "account_wide_flatness_verified":True,
            "watchdog_and_collector_active":True,
            "both_dashboard_fire_endpoints_disabled":True,
            "trade_authorized":False}
        self.assertTrue(check_candidate(self.root,
            broker_factory=lambda **kw:ReadOnly(),
            preflight=lambda broker,root,**kwargs:approved,
            margin_proof=lambda broker: True))
        denied=dict(approved)
        denied["signed_isolated_margin_verified"]=False
        self.assertFalse(check_candidate(self.root,
            broker_factory=lambda **kw:ReadOnly(),
            preflight=lambda broker,root,**kwargs:denied,
            margin_proof=lambda broker: True))

    def test_autonomous_candidate_uses_signed_readonly_broker(self):
        from unittest.mock import patch
        from tradebot.btc_autonomous_demo import check_candidate
        from tradebot.delta import DEMO_API
        class Readonly:
            base_url = DEMO_API
            allow_orders = False
        seen = []
        def broker_factory(**kwargs):
            seen.append(kwargs)
            return Readonly()
        candidate = {
            "status": "operator_review_candidate_only", "blockers": [],
            "supervised_session_verified": True,
            "recent_btc_history_local_quality_verified": True,
            "signed_isolated_margin_verified": True,
            "margin_evidence_source": "signed_parent_subaccount",
            "owner_declared_main_isolated_accepted": False,
            "account_wide_flatness_verified": True,
            "watchdog_and_collector_active": True,
            "both_dashboard_fire_endpoints_disabled": True,
            "trade_authorized": False,
        }
        with patch.dict("os.environ", {
                "DELTA_DEMO_API_KEY": "fake-id",
                "DELTA_DEMO_API_SECRET": "fake-signature"}):
            result = check_candidate(
                self.root, broker_factory=broker_factory,
                preflight=lambda b, p, **kwargs: candidate,
                margin_proof=lambda b: True)
        self.assertTrue(result)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["api_key"], "fake-id")
        self.assertEqual(seen[0]["api_secret"], "fake-signature")
        self.assertIs(seen[0]["allow_orders"], False)

    def test_prior_fire_receipt_rejects_invalid_model_and_unknown_exposure(self):
        from tradebot.btc_autonomous_demo import prior_fire_receipts_safe
        import sqlite3,json
        with sqlite3.connect(self.root/"fire-ops.sqlite") as db:
            db.executescript("""CREATE TABLE fire_requests(
                press TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT,
                status TEXT, result TEXT);""")
            db.execute("INSERT INTO fire_requests VALUES(?,?,?,?,?)",(
                "one",NOW.isoformat(),NOW.isoformat(),
                "rejected_no_order",json.dumps({"reason_code":"model_decision_failed"})))
        self.assertFalse(prior_fire_receipts_safe(self.root))
        with sqlite3.connect(self.root/"fire-ops.sqlite") as db:
            db.execute("UPDATE fire_requests SET result=? WHERE press='one'",
                       (json.dumps({"reason_code":"gpt6_wait_no_trade"}),))
        self.assertTrue(prior_fire_receipts_safe(self.root))
        with sqlite3.connect(self.root/"fire-ops.sqlite") as db:
            db.execute("UPDATE fire_requests SET status='protected_active' WHERE press='one'")
        self.assertFalse(prior_fire_receipts_safe(self.root))

    def test_prior_fire_receipt_rejects_emergency_flat(self):
        from tradebot.btc_autonomous_demo import prior_fire_receipts_safe
        import sqlite3,json
        with sqlite3.connect(self.root/"fire-ops.sqlite") as db:
            db.executescript("""CREATE TABLE fire_requests(
                press TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT,
                status TEXT, result TEXT);""")
            db.execute("INSERT INTO fire_requests VALUES(?,?,?,?,?)",(
                "one",NOW.isoformat(),NOW.isoformat(),
                "flat_verified",json.dumps({"reason_code":"emergency_flat_verified"})))
        self.assertFalse(prior_fire_receipts_safe(self.root))
