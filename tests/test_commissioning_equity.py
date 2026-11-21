"""Offline commissioning risk checks against real isolated SQLite ledgers."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from equity_fixtures import receipt_for
from tradebot.commissioning_equity import signed_equity_readiness
from tradebot.delta import DEMO_API
from tradebot.equity_monitor import MonitorStore, risk_health
from tradebot.equity_receipt import EquityReadError
from tradebot.portfolio_equity_guard import PortfolioEquityGuard, EquityRiskError


class CommissioningEquityTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "fire-equity-risk.sqlite"
        self.now = datetime(2026, 11, 23, 0, 10, tzinfo=timezone.utc)  # Monday
        self.guard = PortfolioEquityGuard(self.path)
        self.monitor = MonitorStore(self.root / "fire-monitoring.sqlite")
        for service in ("watchdog", "equity_collector"):
            self.monitor.heartbeat(service, at=self.now)
        self.exchange = Mock(base_url=DEMO_API, allow_orders=False)
        self.wallet()

    def wallet(self, equity="1000", *, at=None):
        self.exchange.wallet_balances.return_value = {
            "meta": {"net_equity": equity},
            "equity_read_receipt": receipt_for(equity, at or self.now),
        }

    def seed(self, opening="1000", latest="1000"):
        for equity, at in ((opening, self.now.replace(minute=1)),
                           (latest, self.now - timedelta(seconds=1))):
            self.guard.observe_verified_read(equity, receipt_for(equity, at), now=at)

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as db:
            return "\n".join(db.iterdump())

    def check(self):
        return signed_equity_readiness(self.exchange, self.root, now=self.now)

    def test_fresh_risk_approval_has_no_authority_and_does_not_write_evidence(self):
        self.seed()
        before = self.snapshot()
        self.wallet("1100")
        report = self.check()
        self.assertTrue(report["approved"])
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["evidence_persisted"])
        self.assertEqual(report["observed_high_watermark_usd"], "1100")
        self.assertEqual(self.snapshot(), before)  # no new sample or changed peak
        self.assertEqual(len(self.exchange.mock_calls), 1)
        self.exchange.wallet_balances.assert_called_once_with()
        self.assertEqual(self.check()["reason"], report["reason"])  # restart/repeat safe
        self.assertEqual(self.snapshot(), before)

    def test_unsigned_opening_is_blocked_by_hardened_health_before_wallet(self):
        open_at = self.now.replace(minute=1)
        latest_at = self.now - timedelta(seconds=1)
        self.guard.observe("1000", at=open_at)  # legacy origin label, no receipt
        self.guard.observe_verified_read("1000", receipt_for("1000", latest_at),
                                         now=latest_at)
        health = risk_health(self.path, at=self.now)
        self.assertFalse(health["checkpoint_prerequisites_met"])
        self.assertEqual(health["daily_checkpoint"], "unverified_receipt")
        before = self.snapshot()
        result = self.check()
        self.assertFalse(result["approved"])
        self.assertFalse(result["trade_authorized"])
        self.assertEqual(result["reason"], "equity_or_monitoring_prerequisites_missing")
        self.exchange.wallet_balances.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_unsigned_latest_sample_cannot_pass_commissioning(self):
        open_at = self.now.replace(minute=1)
        self.guard.observe_verified_read("1000", receipt_for("1000", open_at),
                                         now=open_at)
        self.guard.observe("1000", at=self.now - timedelta(seconds=1))
        health = risk_health(self.path, at=self.now)
        self.assertFalse(health["checkpoint_prerequisites_met"])
        self.assertEqual(health["latest_receipt_status"], "missing")
        result = self.check()
        self.assertFalse(result["approved"])
        self.assertFalse(result["trade_authorized"])
        self.exchange.wallet_balances.assert_not_called()

    def test_forged_historical_receipt_equity_does_not_validate_anchor(self):
        open_at = self.now.replace(minute=1)
        latest_at = self.now - timedelta(seconds=1)
        self.guard.observe("1000", at=open_at)
        forged = receipt_for("2000", open_at)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO equity_read_receipts VALUES (?,?)",
                       (int(open_at.timestamp() * 1_000_000),
                        __import__("json").dumps(forged)))
        self.guard.observe_verified_read("1000", receipt_for("1000", latest_at),
                                         now=latest_at)
        health = risk_health(self.path, at=self.now)
        self.assertFalse(health["checkpoint_prerequisites_met"])
        self.assertEqual(health["daily_checkpoint"], "unverified_receipt")
        result = self.check()
        self.assertFalse(result["approved"])
        self.assertFalse(result["trade_authorized"])
        self.exchange.wallet_balances.assert_not_called()

    def test_missing_receipt_inserted_during_wallet_read_blocks_final_snapshot(self):
        self.seed()
        wallet = self.exchange.wallet_balances.return_value
        def append_unreceipted_equity():
            self.guard.observe("1000", at=self.now - timedelta(milliseconds=100))
            return wallet
        self.exchange.wallet_balances.side_effect = append_unreceipted_equity
        # Pretend a cached health read stays green across the wallet network
        # operation: the final independent SQLite transaction must still
        # reject the newly introduced unsigned observation.
        initially_healthy = risk_health(self.path, at=self.now)
        self.assertTrue(initially_healthy["checkpoint_prerequisites_met"])
        with patch("tradebot.commissioning_equity.risk_health",
                   return_value=initially_healthy):
            with self.assertRaisesRegex(EquityRiskError, "equity_checkpoint_receipt_missing"):
                self.check()
        self.exchange.wallet_balances.assert_called_once_with()

    def test_exact_daily_limit_blocks_before_consuming_commissioning_attempt(self):
        self.seed()
        self.wallet("980")
        before = self.snapshot()
        result = self.check()
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "loss_limit_daily")
        self.assertEqual(result["limits"], {"daily":"0.02", "weekly":"0.05", "drawdown":"0.08"})
        self.assertEqual(self.snapshot(), before)

    def test_peak_drawdown_remains_independent_of_daily_and_weekly_limits(self):
        self.guard.observe("1100", at=self.now - timedelta(days=1))
        self.seed()
        result = self.check()
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "loss_limit_drawdown")

    def test_weekly_limit_not_rebased_by_todays_opening(self):
        self.now += timedelta(days=1)
        monday_open = datetime(2026, 11, 23, 0, 1, tzinfo=timezone.utc)
        self.guard.observe_verified_read("1100", receipt_for("1100", monday_open),
                                         now=monday_open)
        self.seed(opening="1050", latest="1050")
        self.wallet("1045")
        for service in ("watchdog", "equity_collector"):
            self.monitor.heartbeat(service, at=self.now)
        result = self.check()
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "loss_limit_weekly")

    def test_lowered_historical_peak_blocks_before_wallet_without_repair(self):
        self.guard.observe("1100", at=self.now - timedelta(days=1))
        self.seed()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE equity_watermark SET high_usd='1000' WHERE singleton=1")
        before = self.snapshot()
        result = self.check()
        self.assertFalse(result["approved"])
        self.assertEqual(result["health"]["database_integrity"], "failed")
        self.exchange.wallet_balances.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_final_readonly_snapshot_rejects_peak_lowered_after_health_checks(self):
        self.guard.observe("1100", at=self.now - timedelta(days=1))
        self.seed()
        health = risk_health(self.path, at=self.now)
        self.assertTrue(health["checkpoint_prerequisites_met"])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE equity_watermark SET high_usd='1000' WHERE singleton=1")
        before = self.snapshot()
        # Simulate previously healthy snapshots; the final DB transaction must
        # independently validate history even when those snapshots were sound.
        with patch("tradebot.commissioning_equity.risk_health", return_value=health):
            with self.assertRaisesRegex(EquityRiskError, "watermark_inconsistent"):
                self.check()
        self.exchange.wallet_balances.assert_called_once_with()
        self.assertEqual(self.snapshot(), before)

    def test_equity_ledger_replacement_after_health_is_rejected_before_wallet(self):
        self.seed()
        original_health = risk_health
        preserved = self.root / "preserved-original.sqlite"
        def replaced_health(path, *, at=None):
            result = original_health(path, at=at)
            self.path.rename(preserved)
            self.path.write_bytes(b"untrusted replacement")
            return result
        with patch("tradebot.commissioning_equity.risk_health",
                   side_effect=replaced_health):
            with self.assertRaisesRegex(EquityRiskError, "equity_ledger_replaced"):
                self.check()
        self.exchange.wallet_balances.assert_not_called()
        self.assertEqual(self.path.read_bytes(), b"untrusted replacement")

    def test_equity_ledger_replacement_during_wallet_read_is_rejected(self):
        self.seed()
        preserved = self.root / "preserved-original.sqlite"
        wallet = self.exchange.wallet_balances.return_value
        def replaced_wallet():
            self.path.rename(preserved)
            self.path.write_bytes(b"untrusted replacement")
            return wallet
        self.exchange.wallet_balances.side_effect = replaced_wallet
        with self.assertRaisesRegex(EquityRiskError, "equity_ledger_replaced"):
            self.check()
        self.exchange.wallet_balances.assert_called_once_with()
        self.assertEqual(self.path.read_bytes(), b"untrusted replacement")

    def test_equity_ledger_replacement_during_final_calculation_is_rejected(self):
        self.seed()
        preserved = self.root / "preserved-original.sqlite"
        from tradebot.portfolio_equity_guard import assess_equity as original_assess
        def replaced_assessment(*args, **kwargs):
            report = original_assess(*args, **kwargs)
            self.path.rename(preserved)
            self.path.write_bytes(b"untrusted replacement")
            return report
        with patch("tradebot.commissioning_equity.assess_equity",
                   side_effect=replaced_assessment):
            with self.assertRaisesRegex(EquityRiskError, "equity_ledger_replaced"):
                self.check()
        self.exchange.wallet_balances.assert_called_once_with()
        self.assertEqual(self.path.read_bytes(), b"untrusted replacement")

    def test_missing_openings_never_use_the_later_wallet(self):
        self.guard.observe("1000", at=self.now)
        before = self.snapshot()
        result = self.check()
        self.assertFalse(result["approved"])
        self.assertEqual(result["health"]["daily_checkpoint"], "missed_window")
        self.assertEqual(result["health"]["weekly_checkpoint"], "missed_window")
        self.exchange.wallet_balances.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_stale_watchdog_or_observation_blocks_wallet_read(self):
        self.seed()
        self.now += timedelta(minutes=4)
        self.assertFalse(self.check()["approved"])
        self.exchange.wallet_balances.assert_not_called()

    def test_clock_or_authentication_incident_blocks_readiness(self):
        self.seed()
        for code in ("system_clock_unverified", "broker_authentication_failed"):
            with self.subTest(code=code):
                self.monitor.heartbeat("equity_collector", code, at=self.now)
                self.assertFalse(self.check()["approved"])
        self.exchange.wallet_balances.assert_not_called()

    def test_stale_or_forged_transport_metadata_is_not_fresh_equity(self):
        self.seed()
        self.wallet(at=self.now - timedelta(seconds=31))
        with self.assertRaises(EquityReadError):
            self.check()
        self.wallet()
        self.exchange.wallet_balances.return_value["equity_read_receipt"]["equity_usd"] = "2000"
        with self.assertRaises(EquityReadError):
            self.check()

    def test_health_is_rechecked_after_wallet_network_operation(self):
        self.seed()
        health = risk_health(self.path, at=self.now)
        with patch("tradebot.commissioning_equity.risk_health",
                   side_effect=[health, {**health, "checkpoint_prerequisites_met":False}]):
            self.assertFalse(self.check()["approved"])
        self.exchange.wallet_balances.assert_called_once_with()

    def test_wallet_older_than_concurrent_collector_observation_is_rejected(self):
        self.seed()
        self.wallet(at=self.now - timedelta(seconds=2))
        with self.assertRaisesRegex(EquityRiskError, "out_of_order"):
            self.check()

    def test_readonly_client_required_before_any_access(self):
        for url, allow in (("https://api.india.delta.exchange", False), (DEMO_API, True), (DEMO_API, 0)):
            self.exchange.base_url, self.exchange.allow_orders = url, allow
            with self.assertRaises(EquityRiskError):
                self.check()
        self.assertEqual(self.exchange.mock_calls, [])

    def test_missing_database_is_not_created_and_corruption_not_repaired(self):
        missing = self.root / "missing"
        result = signed_equity_readiness(self.exchange, missing, now=self.now)
        self.assertFalse(result["approved"])
        self.assertFalse(missing.exists())
        # An unrelated corrupt evidence file is preserved byte-for-byte.
        broken = self.root / "broken"
        broken.mkdir()
        file = broken / self.path.name
        file.write_bytes(b"corrupt original equity evidence")
        self.assertFalse(signed_equity_readiness(self.exchange, broken, now=self.now)["approved"])
        self.assertEqual(file.read_bytes(), b"corrupt original equity evidence")
        self.assertEqual(self.exchange.mock_calls, [])

    def test_ro_schema_compatibility_and_loss_calculation_match_ingestion(self):
        self.seed()
        before = self.snapshot()
        self.wallet("990")
        actual = self.check()
        self.assertEqual(self.snapshot(), before)
        other = PortfolioEquityGuard(self.root / "isolated-comparison.sqlite")
        other.observe("1000", at=self.now.replace(minute=1))
        expected = other.observe("990", at=self.now)
        for key, value in expected.items():
            self.assertEqual(actual[key], value, key)


if __name__ == "__main__":
    unittest.main()
