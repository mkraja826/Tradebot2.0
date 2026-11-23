"""Gold unattended worker: 5-minute post-close cooldown, independent account, guarded order authority."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock,patch
import json
import os
import sqlite3
import unittest

from tradebot.gold_autonomous_demo import (
    ARM_CONTENT,claim_attempt,run_once,is_gold_armed,
    receipts_safe,check_candidate)
from tradebot.gold_autonomous_controller import AutoGoldController, gold_deepseek_adapter
from tradebot.gold_deepseek_probe import GOLD_ROLES
from tradebot.fire_probe import ROLES


NOW=datetime(2026,11,23,5,30,tzinfo=timezone.utc)


class GoldAutonomousTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)/"gold-isolated"
        self.root.mkdir()
        self.root.chmod(0o700)

    def test_gold_fire_snapshot_loader_receives_gold_symbol(self):
        with patch("tradebot.gold_autonomous_controller.load_snapshot",
                   side_effect=lambda symbol: {"symbol": symbol}) as loader:
            bot=AutoGoldController(self.root/"fire-xaut.sqlite",enabled=False)
            self.assertEqual(bot.snapshot_loader("XAUTUSD"),{"symbol":"XAUTUSD"})
            loader.assert_called_once_with("XAUTUSD")

    def test_broker_leverage_at_20x_is_supported_by_gold_controller(self):
        bot=AutoGoldController(self.root/"fire-xaut.sqlite",enabled=False)
        self.assertEqual(bot._hard_contract_cap(),6)
        self.assertEqual(bot._decision_model_id(),"tb-deepseek-v4-1-flash")

    def test_unique_gold_arm_cannot_be_btc_authorization(self):
        arm=self.root/"gold_arm"
        arm.write_text(ARM_CONTENT+"\n")
        arm.chmod(0o600)
        self.assertTrue(is_gold_armed(arm))
        arm.write_text("DELTA-INDIA-DEMO:BTCUSD:UNATTENDED:30MIN-MAX48-DYNAMIC6\n")
        self.assertFalse(is_gold_armed(arm))
        arm.write_text(ARM_CONTENT+"\n")
        arm.chmod(0o644)
        self.assertFalse(is_gold_armed(arm))

    def test_same_5_minute_spacing_without_daily_count_cap(self):
        t=NOW
        for i in range(100):
            when=t+timedelta(minutes=5*i)
            self.assertIsNotNone(claim_attempt(self.root,when))
            self.assertIsNone(claim_attempt(
                self.root,when+timedelta(minutes=4)))
        with sqlite3.connect(self.root/"gold-auto-demo.sqlite") as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM gold_auto_attempts WHERE utc_day=?",
                (t.date().isoformat(),)).fetchone()[0],100)
        self.assertFalse((self.root/"btc-auto-demo.sqlite").exists())

    def test_btc_model_is_unmodified_and_gold_routes_deepseek_only(self):
        self.assertEqual(ROLES,{"fire":"tb-gpt-6"})
        self.assertEqual(GOLD_ROLES,{"fire":"tb-deepseek-v4-1-flash"})
        with patch("tradebot.gold_autonomous_controller.run_gold_deepseek_probe",
                   return_value={"results":{"fire":{"decision":"test"}}}) as p:
            self.assertEqual(gold_deepseek_adapter(ROLES,lambda:None)
                             ["results"]["fire"]["decision"],"test")
            p.assert_called_once()
            self.assertEqual(p.call_args.args[0],GOLD_ROLES)
        with self.assertRaises(ValueError):
            gold_deepseek_adapter(GOLD_ROLES,lambda:None)

    def test_no_order_without_isolated_gold_arm(self):
        self.assertEqual(run_once(self.root,armed=lambda:False,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0)),
                         {"status":"disarmed"})
        self.assertFalse((self.root/"gold-auto-demo.sqlite").exists())

    def test_migration_halt_blocks_every_attempt(self):
        (self.root/"gold-auto-demo-halt").touch()
        self.assertEqual(run_once(self.root,armed=lambda:True,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0)),
                         {"status":"halted_pending_operator_review"})
        self.assertFalse((self.root/"gold-auto-demo.sqlite").exists())

    def test_nonflat_broker_account_skips_not_fires(self):
        state=run_once(self.root,armed=lambda:True,candidate=lambda x:False,
            active_trade_probe=lambda x:True,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0))
        self.assertEqual(state["status"],"skipped_active_trade")
        self.assertFalse((self.root/"gold-auto-demo.sqlite").exists())

    def test_unverified_broker_cannot_force_trade(self):
        state=run_once(self.root,armed=lambda:True,candidate=lambda x:False,
            active_trade_probe=lambda x:None,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0))
        self.assertEqual(state["status"],"read_only_preflight_unavailable")
        self.assertFalse((self.root/"gold-auto-demo.sqlite").exists())

    def test_true_readonly_candidate_never_reserves_attempt(self):
        state=run_once(self.root,armed=lambda:True,candidate=lambda x:True,
            receipt_check=lambda x:True,do_execute=False)
        self.assertEqual(state["status"],"eligible_read_only_no_order")
        self.assertFalse((self.root/"gold-auto-demo.sqlite").exists())

    def test_protected_deepseek_execution_retains_gold_watchdog_authority(self):
        fake=Mock()
        fake.start.return_value=(True,"accepted")
        fake.snapshot.return_value={
            "status":"protected_active","orders_submitted":True,
            "protection_verified":True,"liquidation_verified":True}
        run=run_once(self.root,instant=NOW,armed=lambda:True,
            candidate=lambda x:True,receipt_check=lambda x:True,
            controller_factory=lambda *a,**k:fake,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0))
        self.assertTrue(run["protected"])
        self.assertEqual(run["status"],"attempt_finished")
        self.assertEqual(run["result"],"protected_active")
        self.assertFalse((self.root/"gold-auto-demo-halt").exists())
        self.assertTrue((self.root/"gold-auto-demo.sqlite").exists())
        self.assertFalse((self.root/"btc-auto-demo.sqlite").exists())
        self.assertEqual(fake.start.call_count,1)

    def test_unknown_protection_status_halts_isolated_gold_only(self):
        fake=Mock()
        fake.start.return_value=(True,"accepted")
        fake.snapshot.return_value={
            "status":"exposure_unknown","orders_submitted":True,
            "protection_verified":False}
        result=run_once(self.root,instant=NOW,armed=lambda:True,
            candidate=lambda x:True,receipt_check=lambda x:True,
            controller_factory=lambda *a,**k:fake,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0))
        self.assertEqual(result["result"],"exposure_unknown")
        self.assertTrue((self.root/"gold-auto-demo-halt").is_file())
        self.assertFalse((self.root/"btc-auto-demo-halt").exists())

    def test_gold_no_order_risk_rejection_is_retryable_without_halt(self):
        fake=Mock()
        fake.start.return_value=(True,"accepted")
        fake.snapshot.return_value={
            "status":"rejected_no_order","orders_submitted":False,
            "reason_code":"risk_governor_failed",
            "protection_verified":False}
        response=run_once(self.root,instant=NOW,armed=lambda:True,
            candidate=lambda x:True,receipt_check=lambda x:True,
            controller_factory=lambda *a,**k:fake,do_execute=True,cooldown_check=lambda *args,**kwargs:("ready",0))
        self.assertEqual(response["result"],"rejected_no_order")
        self.assertFalse(response["orders_submitted"])
        self.assertFalse((self.root/"gold-auto-demo-halt").exists())

    def test_gold_prior_safe_no_order_receipt_may_retry_after_five_minutes(self):
        db=self.root/"fire-xaut.sqlite"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE fire_requests("
                         "press TEXT,status TEXT,result TEXT,created_at TEXT)")
            conn.execute("INSERT INTO fire_requests VALUES(?,?,?,?)",
                         ("x","rejected_no_order",json.dumps({
                            "orders_submitted":False,
                            "protection_verified":False,
                            "reason_code":"risk_governor_failed"}),NOW.isoformat()))
        self.assertTrue(receipts_safe(self.root))
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE fire_requests SET result=?",
                (json.dumps({"orders_submitted":True,
                    "protection_verified":False,
                    "reason_code":"risk_governor_failed"}),))
        self.assertFalse(receipts_safe(self.root))

    def test_unknown_no_order_reason_requires_review(self):
        db=self.root/"fire-xaut.sqlite"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE fire_requests("
                         "press TEXT,status TEXT,result TEXT,created_at TEXT)")
            conn.execute("INSERT INTO fire_requests VALUES(?,?,?,?)",
                         ("x","rejected_no_order",json.dumps({
                            "orders_submitted":False,
                            "protection_verified":False,
                            "reason_code":"execution_or_protection_unverified"}),NOW.isoformat()))
        self.assertFalse(receipts_safe(self.root))

    def test_no_ledger_history_with_unknown_receipt_is_replayed(self):
        import sqlite3
        db=self.root/"fire-xaut.sqlite"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE fire_requests("
                         "press TEXT,status TEXT,result TEXT,created_at TEXT)")
            conn.execute("INSERT INTO fire_requests VALUES(?,?,?,?)",
                         ("x","protected_active","{}",NOW.isoformat()))
        self.assertFalse(receipts_safe(self.root))

    def test_gold_credential_scope_and_signed_flat_recheck(self):
        bot=AutoGoldController(self.root/"fire-xaut.sqlite",enabled=False)
        with patch("tradebot.gold_autonomous_demo.is_gold_armed",
                   return_value=True):
            with patch.dict(os.environ,
                            {"TRADEBOT_EXPECTED_DEMO_SUBACCOUNT":"GOLD"}):
                with patch("tradebot.gold_autonomous_controller.signed_account_margin_mode",
                           return_value="isolated"):
                    with patch("tradebot.gold_autonomous_controller.require_flat_demo_account",
                               return_value={"account_flat_verified":True}) as flat:
                        broker=Mock(base_url="https://cdn-ind.test")
                        from tradebot.delta import DEMO_API
                        broker.base_url=DEMO_API
                        result=bot._require_account_flat(broker,908)
                        self.assertTrue(result["account_flat_verified"])
                        self.assertEqual(flat.call_args.kwargs["selected_symbol"],"XAUTUSD")
                        self.assertEqual(flat.call_args.kwargs["selected_product_id"],908)
            with patch.dict(os.environ,
                            {"TRADEBOT_EXPECTED_DEMO_SUBACCOUNT":"BTC"}):
                with self.assertRaisesRegex(ValueError,"gold_isolated_account_scope"):
                    bot._require_account_flat(Mock(),908)

    def test_gold_uses_same_chart_derived_warning_only_loss_policy(self):
        bot=AutoGoldController(self.root/"fire-xaut.sqlite",enabled=False)
        self.assertEqual(bot._hard_contract_cap(),6)
        self.assertFalse(bot._allow_wait_choice())
        self.assertEqual(bot._decision_model_id(),"tb-deepseek-v4-1-flash")
        self.assertTrue(bot.equity_guard.allow_portfolio_loss_warnings)
        self.assertTrue(bot.equity_guard.allow_initial_isolated_genesis)
        self.assertEqual(bot.equity_guard.isolated_genesis_account,"GOLD")


if __name__=="__main__":
    unittest.main()
