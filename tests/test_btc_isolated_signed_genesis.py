"""Strict first-day signed BTC DEMO genesis admission; never backdate."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from equity_fixtures import receipt_for
from tradebot.btc_supervised_session import (
    isolated_btc_signed_genesis_window, inspect_btc_session_candidate,
)
from tradebot.btc_supervised_equity_guard import SupervisedSessionEquityGuard
from tradebot.portfolio_equity_guard import PortfolioEquityGuard, EquityRiskError
from tradebot.delta import DEMO_API


class SignedGenesisTests(unittest.TestCase):
    def setUp(self):
        t = TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.child = self.root / "btc-isolated"
        self.child.mkdir()
        self.path = self.child / "fire-equity-risk.sqlite"
        self.first_at = datetime(2026,11,23,4,30,tzinfo=timezone.utc)
        self.now = self.first_at + timedelta(minutes=2)
        self.first_receipt = receipt_for("100",self.first_at)
        PortfolioEquityGuard(self.path).observe_verified_read(
            "100",self.first_receipt,now=self.first_at)
        self.health = {
            "daily_checkpoint":"missed_window",
            "weekly_checkpoint":"missed_window",
            "database_integrity":"verified",
            "latest_receipt_status":"verified",
            "observation_status":"fresh",
            "blocking_conditions":[
                "daily_checkpoint_missed_window",
                "weekly_checkpoint_missed_window"],
            "monitoring":{
                "watchdog":"healthy",
                "equity_collector":"healthy",
                "watchdog_age_seconds":2.0,
                "equity_collector_age_seconds":5.0,
                "alert_codes":[],
            },
        }

    def proof(self, instant=None):
        with patch.dict("os.environ",{
                "TRADEBOT_EXPECTED_DEMO_SUBACCOUNT":"BTC"}):
            return isolated_btc_signed_genesis_window(
                self.path,self.health,instant or self.now)

    def test_real_first_day_receipt_and_watermark_pass_provisionally(self):
        self.assertTrue(self.proof())
        self.assertFalse(self.health["daily_checkpoint"] == "verified")

    def test_exception_expires_at_next_midnight(self):
        self.assertFalse(self.proof(datetime(
            2026,11,24,0,0,tzinfo=timezone.utc)))

    def test_wrong_account_and_wrong_data_directory_rejected(self):
        with patch.dict("os.environ",{
                "TRADEBOT_EXPECTED_DEMO_SUBACCOUNT":"GOLD"}):
            self.assertFalse(isolated_btc_signed_genesis_window(
                self.path,self.health,self.now))
        other = self.root / "gold-isolated"
        other.mkdir()
        fake = other / "fire-equity-risk.sqlite"
        fake.write_bytes(self.path.read_bytes())
        with patch.dict("os.environ",{
                "TRADEBOT_EXPECTED_DEMO_SUBACCOUNT":"BTC"}):
            self.assertFalse(isolated_btc_signed_genesis_window(
                fake,self.health,self.now))

    def test_unknown_blockers_and_missing_receipt_fail_closed(self):
        self.health["blocking_conditions"].append("equity_evidence_unavailable")
        self.assertFalse(self.proof())
        self.health["blocking_conditions"].pop()
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM equity_read_receipts")
        self.assertFalse(self.proof())

    def test_first_day_start_cannot_pretend_to_be_midnight(self):
        self.health["daily_checkpoint"] = "verified"
        self.assertFalse(self.proof())

    def test_readonly_session_reports_provisional_not_fake_daily(self):
        class Broker:
            base_url=DEMO_API
            allow_orders=False
            def wallet_balances(_self):
                return {"meta":{"net_equity":"100"},
                        "equity_read_receipt":receipt_for("100",self.now)}
        def health_fn(path, *,at):
            self.assertEqual(path,self.path)
            return self.health
        with patch.dict("os.environ",{
                "TRADEBOT_EXPECTED_DEMO_SUBACCOUNT":"BTC"}):
            accepted=inspect_btc_session_candidate(
                Broker(),self.child,now=self.now,health_fn=health_fn,
                allow_portfolio_loss_warnings=True,
                allow_daily_loss_warning=True,
                allow_initial_isolated_genesis=True)
            normal=inspect_btc_session_candidate(
                Broker(),self.child,now=self.now,health_fn=health_fn,
                allow_portfolio_loss_warnings=True,
                allow_daily_loss_warning=True)
        self.assertEqual(accepted["status"],"baseline_candidate_review_only")
        self.assertTrue(accepted["provisional_first_day_signed_genesis"])
        self.assertFalse(accepted["daily_checkpoint_verified"])
        self.assertIn("provisional_first_day_signed_genesis",
                      accepted["quality_warnings"])
        self.assertEqual(normal["status"],"blocked")
        self.assertFalse(accepted["trade_authorized"])

    def test_execution_guard_uses_identical_proof_not_unverified_health(self):
        with patch.dict("os.environ",{
                "TRADEBOT_EXPECTED_DEMO_SUBACCOUNT":"BTC"}):
            verifier = SupervisedSessionEquityGuard(
                self.path,health_fn=lambda path,at:self.health,
                allow_daily_loss_warning=True,
                allow_portfolio_loss_warnings=True,
                allow_initial_isolated_genesis=True)
            good=verifier.require_verified_read(
                "100",receipt_for("100",self.now),now=self.now)
            self.assertTrue(good["provisional_first_day_signed_genesis"])
            self.assertFalse(good["daily_checkpoint_verified"])
            strict=SupervisedSessionEquityGuard(
                self.path,health_fn=lambda path,at:self.health,
                allow_daily_loss_warning=True,
                allow_portfolio_loss_warnings=True)
            with self.assertRaises(EquityRiskError):
                strict.require_verified_read(
                    "100",receipt_for("100",self.now),now=self.now)


if __name__=="__main__":
    unittest.main()
