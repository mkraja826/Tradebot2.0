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

    def test_loss_alerts_warning_only_do_not_hide_watchdog_failure(self):
        from tradebot.equity_monitor import demo_monitoring_operational
        monitor = {
            "watchdog": "healthy", "equity_collector": "healthy",
            "watchdog_age_seconds": 3, "equity_collector_age_seconds": 6,
            "alert_codes": ["equity_loss_limit_breached",
                            "equity_daily_loss_limit_breached"],
        }
        self.assertFalse(demo_monitoring_operational(
            monitor, allow_daily_loss_warning=True))
        self.assertTrue(demo_monitoring_operational(
            monitor, allow_daily_loss_warning=True,
            allow_portfolio_loss_warnings=True))
        self.assertFalse(demo_monitoring_operational(
            {**monitor, "alert_codes": monitor["alert_codes"] +
             ["watchdog_protection_unverified"]},
            allow_daily_loss_warning=True,
            allow_portfolio_loss_warnings=True))
        self.assertFalse(demo_monitoring_operational(
            {**monitor, "watchdog": "stale"},
            allow_daily_loss_warning=True,
            allow_portfolio_loss_warnings=True))

    def seed_ledger(self):
        path = self.root / "fire-equity-risk.sqlite"
        guard = PortfolioEquityGuard(path)
        # Synthetic pre-existing history, older than the current live clock.
        guard.observe("1000", at=datetime.now(timezone.utc) - timedelta(days=8))
        return guard

    def test_demo_loss_events_are_warnings_but_protection_failures_are_critical(self):
        codes = ["equity_daily_loss_limit_breached", "equity_loss_limit_breached",
                 "watchdog_protection_unverified", "broker_authentication_failed"]
        severity = {event["code"]: event["severity"]
                    for event in self.store.publish(codes, at=self.now)}
        self.assertEqual(severity, dict(zip(codes, ["warning", "warning", "critical", "critical"])))

    def test_events_are_deduplicated_and_recover_across_restarts(self):
        code = "broker_authentication_failed"
        self.assertEqual(self.store.publish([code], at=self.now)[0]["transition"], "opened")
        new = MonitorStore(self.path)
        self.assertEqual(new.publish([code], at=self.now + timedelta(seconds=299)), [])
        self.assertEqual(new.publish([code], at=self.now + timedelta(seconds=300))[0]["transition"], "reminder")
        events = new.publish([], at=self.now + timedelta(seconds=301))
        self.assertEqual(events[0]["transition"], "resolved")
        self.assertEqual(new.publish([], at=self.now + timedelta(seconds=302)), [])

    def test_durable_emergency_closeout_is_exact_once_and_does_not_leak_press(self):
        press = "a" * 32
        event = self.store.record_watchdog_emergency(press, at=self.now)
        self.assertEqual(event["code"], "watchdog_emergency_flat_verified")
        self.assertEqual(event["transition"], "opened")
        self.assertEqual(event["severity"], "critical")
        self.assertNotIn(press, json.dumps(event))
        self.assertIsNone(
            MonitorStore(self.path).record_watchdog_emergency(
                press, at=self.now + timedelta(seconds=1)))
        # Collector reconciles active alerts independently, without deleting
        # the historical emergency closeout event from the outbox.
        self.store.publish(["missed_weekly_checkpoint"], at=self.now)
        self.store.publish([], at=self.now + timedelta(seconds=10))
        with sqlite3.connect(self.path) as db:
            incidents = db.execute(
                "SELECT id,at_us,code,transition,severity FROM monitor_events "
                "WHERE code='watchdog_emergency_flat_verified'").fetchall()
            claimed = db.execute(
                "SELECT event_id FROM watchdog_emergency_events WHERE press=?",
                (press,)).fetchone()
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0][0], claimed[0])
        self.assertEqual(incidents[0][3:], ("opened", "critical"))

    def test_concurrent_emergency_event_replays_are_deduplicated(self):
        press = "b" * 32
        def replay(_):
            return MonitorStore(self.path).record_watchdog_emergency(
                press, at=self.now)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(replay, range(12)))
        self.assertEqual(sum(event is not None for event in results), 1)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM watchdog_emergency_events"
            ).fetchone()[0], 1)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM monitor_events"
            ).fetchone()[0], 1)

    def test_ambiguous_crash_recovery_alert_has_distinct_persistent_code(self):
        press = "c" * 32
        first = self.store.record_watchdog_emergency(
            press, at=self.now,
            reason_code="watchdog_protection_failure_flat_verified")
        self.assertEqual(first["code"], "watchdog_protection_failure_flat_verified")
        self.assertEqual(first["severity"], "critical")
        self.assertNotIn(press, json.dumps(first))
        self.assertIsNone(self.store.record_watchdog_emergency(
            press, at=self.now + timedelta(seconds=5),
            reason_code="watchdog_emergency_flat_verified"))
        with sqlite3.connect(self.path) as db:
            codes = db.execute(
                "SELECT code FROM monitor_events").fetchall()
        self.assertEqual(codes, [("watchdog_protection_failure_flat_verified",)])

    def test_unknown_watchdog_incident_category_fails_closed(self):
        with self.assertRaises(ValueError):
            self.store.record_watchdog_emergency(
                "d" * 32, reason_code="private_untrusted_reason")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM monitor_events").fetchone()[0], 0)

    def test_invalid_emergency_press_never_creates_event(self):
        for press in ("", "not-an-id", "SECRET_KEY_PRIVATE", "A" * 32, None):
            with self.subTest(press=press):
                with self.assertRaises(ValueError):
                    self.store.record_watchdog_emergency(press)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM monitor_events"
            ).fetchone()[0], 0)

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
        PortfolioEquityGuard(path).observe_verified_read(
            "1000", receipt_for(at=self.now), now=self.now)
        self.store.heartbeat("equity_collector", at=self.now)
        health = risk_health(path, at=self.now)
        self.assertEqual(health["status"], "monitoring_degraded")
        self.assertFalse(health["checkpoint_prerequisites_met"])
        self.assertFalse(health["trade_authorized"])
