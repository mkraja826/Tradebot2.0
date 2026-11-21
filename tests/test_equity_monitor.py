from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from equity_fixtures import receipt_for
from tradebot.delta import DEMO_API, DeltaReadError
from tradebot.equity_monitor import (MonitorStore, collect_once, operations_health,
                                    risk_health, clock_synchronized, main)
from tradebot.portfolio_equity_guard import PortfolioEquityGuard


class MonitorTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "fire-monitoring.sqlite"
        self.store = MonitorStore(self.path)
        self.now = datetime(2026, 11, 23, 0, 1, tzinfo=timezone.utc)

    def seed_ledger(self):
        path = self.root / "fire-equity-risk.sqlite"
        guard = PortfolioEquityGuard(path)
        # Synthetic pre-existing history, older than the current live clock.
        guard.observe("1000", at=datetime.now(timezone.utc) - timedelta(days=8))
        return guard

    def test_events_are_deduplicated_and_recover_across_restarts(self):
        code = "broker_authentication_failed"
        self.assertEqual(self.store.publish([code], at=self.now)[0]["transition"], "opened")
        new = MonitorStore(self.path)
        self.assertEqual(new.publish([code], at=self.now + timedelta(seconds=299)), [])
        self.assertEqual(new.publish([code], at=self.now + timedelta(seconds=300))[0]["transition"], "reminder")
        events = new.publish([], at=self.now + timedelta(seconds=301))
        self.assertEqual(events[0]["transition"], "resolved")
        self.assertEqual(new.publish([], at=self.now + timedelta(seconds=302)), [])

    def test_alert_concurrency_creates_one_outbox_event(self):
        def publish(_):
            return MonitorStore(self.path).publish(["missed_weekly_checkpoint"], at=self.now)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(publish, range(16)))
        self.assertEqual(sum(map(len,results)), 1)

    def test_restart_loop_and_stale_heartbeat_are_detected_by_separate_reader(self):
        for i in range(3):
            self.store.start("watchdog", at=self.now + timedelta(seconds=i))
        self.store.heartbeat("watchdog", at=self.now)
        self.store.heartbeat("equity_collector", at=self.now)
        report = operations_health(self.path, at=self.now + timedelta(seconds=91))
        self.assertEqual(report["watchdog"], "stale")
        self.assertEqual(report["equity_collector"], "healthy")
        self.assertIn("watchdog_restart_loop", report["alert_codes"])
        later = operations_health(self.path, at=self.now + timedelta(minutes=11))
        self.assertNotIn("watchdog_restart_loop", later["alert_codes"])

    def test_clock_reversal_never_yields_healthy_operations(self):
        self.store.heartbeat("watchdog", at=self.now)
        report = operations_health(self.path, at=self.now - timedelta(seconds=1))
        self.assertEqual(report["watchdog"], "unavailable")
        self.assertTrue(report["alert_codes"])

    def test_collector_is_read_only_and_ignores_missing_openings_for_monitoring(self):
        self.seed_ledger()
        now = datetime.now(timezone.utc)
        broker = Mock(base_url=DEMO_API)
        broker.wallet_balances.return_value = {"meta":{"net_equity":"1000"},
                                               "equity_read_receipt":receipt_for(at=now)}
        report, events = collect_once(broker, self.root, clock_check=lambda:True)
        broker.wallet_balances.assert_called_once_with()
        self.assertEqual(len(broker.mock_calls), 1)
        self.assertFalse(report["trade_authorized"])
        self.assertEqual(report["monitoring"]["equity_collector"], "healthy")
        self.assertIn("watchdog_heartbeat_stale", report["alert_codes"])
        self.assertNotIn("1000", json.dumps(events))

    def test_authentication_failure_reports_code_without_upstream_secrets(self):
        old = self.seed_ledger().latest_observed_us()
        broker = Mock(base_url=DEMO_API)
        broker.wallet_balances.side_effect = DeltaReadError("broker_authentication_failed")
        report, _ = collect_once(broker, self.root, clock_check=lambda:True)
        self.assertIn("broker_authentication_failed", report["alert_codes"])
        self.assertEqual(broker.wallet_balances.call_count, 1)
        self.assertEqual(PortfolioEquityGuard(self.root / "fire-equity-risk.sqlite").latest_observed_us(), old)

    def test_clock_failure_blocks_sampling_not_protection(self):
        broker = Mock(base_url=DEMO_API)
        report, _ = collect_once(broker, self.root, clock_check=lambda:False)
        self.assertIn("system_clock_unverified", report["alert_codes"])
        self.assertFalse((self.root / "fire-equity-risk.sqlite").exists())
        self.assertEqual(broker.mock_calls, [])

    def test_os_clock_check_is_bounded_and_requires_explicit_sync(self):
        with patch("tradebot.equity_monitor.subprocess.run", return_value=Mock(returncode=0,stdout="yes\n")) as run:
            self.assertTrue(clock_synchronized())
            self.assertEqual(run.call_args.kwargs["timeout"], 2)
        with patch("tradebot.equity_monitor.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(clock_synchronized())

    def test_corrupt_risk_ledger_preserved_and_does_not_call_broker(self):
        path = self.root / "fire-equity-risk.sqlite"
        path.write_bytes(b"corrupt database evidence")
        broker = Mock(base_url=DEMO_API)
        report, _ = collect_once(broker, self.root, clock_check=lambda:True)
        self.assertIn("equity_database_integrity_failed", report["alert_codes"])
        self.assertEqual(path.read_bytes(), b"corrupt database evidence")
        self.assertEqual(broker.mock_calls, [])

    def test_reconnect_resolves_auth_failure_without_backfilling_history(self):
        self.seed_ledger()
        broker = Mock(base_url=DEMO_API)
        broker.wallet_balances.side_effect = DeltaReadError("broker_authentication_failed")
        collect_once(broker, self.root, clock_check=lambda:True)
        broker.wallet_balances.side_effect = None
        broker.wallet_balances.return_value = {"meta":{"net_equity":"1000"},
                                               "equity_read_receipt":receipt_for()}
        report, events = collect_once(broker, self.root, clock_check=lambda:True)
        self.assertNotIn("broker_authentication_failed", report["alert_codes"])
        self.assertIn({"code":"broker_authentication_failed","transition":"resolved"},
                      [{k:e[k] for k in ("code","transition")} for e in events])
        with sqlite3.connect(self.root / "fire-equity-risk.sqlite") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM equity_evidence").fetchone()[0], 2)

    def test_missing_historical_ledger_is_not_recreated_from_a_current_wallet(self):
        path = self.root / "fire-equity-risk.sqlite"
        self.seed_ledger()
        original = path.read_bytes()
        backup = path.with_name("preserved-risk.sqlite")
        path.rename(backup)
        broker = Mock(base_url=DEMO_API)
        report, _ = collect_once(broker, self.root, clock_check=lambda:True)
        self.assertFalse(report["checkpoint_prerequisites_met"])
        self.assertIn("equity_ledger_unavailable", report["alert_codes"])
        self.assertFalse(path.exists())
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(broker.mock_calls, [])

    def test_read_only_check_does_not_create_or_repair_files(self):
        missing = self.root / "missing"
        with patch("builtins.print"), patch("tradebot.equity_monitor.DeltaDemo") as broker:
            self.assertEqual(main(["--check","--data-dir",str(missing)]), 2)
            broker.assert_not_called()
        self.assertFalse(missing.exists())

    def test_unknown_alert_cannot_leak_secrets(self):
        with self.assertRaises(ValueError):
            self.store.publish(["API_KEY=private"])
        with self.assertRaises(ValueError):
            self.store.heartbeat("watchdog", "API_KEY=private")

    def test_healthy_checkpoints_do_not_hide_missing_watchdog(self):
        path = self.root / "fire-equity-risk.sqlite"
        PortfolioEquityGuard(path).observe("1000", at=self.now)
        self.store.heartbeat("equity_collector", at=self.now)
        health = risk_health(path, at=self.now)
        self.assertEqual(health["status"], "monitoring_degraded")
        self.assertFalse(health["checkpoint_prerequisites_met"])
        self.assertFalse(health["trade_authorized"])
