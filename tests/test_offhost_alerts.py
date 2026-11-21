"""Offline tests for off-machine delivery; no real webhooks or broker access."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import subprocess
import unittest

from tradebot.equity_monitor import MonitorStore
from tradebot.offhost_alerts import (
    AlertRelayError, CURSOR_DB, EVENT_DB, check_only, deliver_once,
    validate_https_destination,
)


class OffHostAlertTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="offhost-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 11, 22, 2, 0, tzinfo=timezone.utc)
        self.events = MonitorStore(self.root / EVENT_DB)
        self.webhook = "https://alerts.example.org/tradebot/private"
        self.ping = "https://healthchecks.example.org/check-in"

    def healthy(self):
        for service in ("watchdog", "equity_collector"):
            self.events.start(service, at=self.now)
            self.events.heartbeat(service, at=self.now)

    def fetch_cursor(self):
        with closing(sqlite3.connect(self.root / CURSOR_DB)) as db:
            return db.execute(
                "SELECT last_event,last_ping_us FROM delivery_cursor WHERE id=1"
            ).fetchone()

    def test_service_scripts_are_no_trade_and_installer_stages_only(self):
        root = Path(__file__).resolve().parents[1]
        launcher_path = root / "ops/run_offhost_alerts.sh"
        installer_path = root / "ops/install_offhost_alerts_service.sh"
        for path in (launcher_path, installer_path):
            with self.subTest(script=path.name):
                result = subprocess.run(
                    ["bash", "-n", str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
        launcher = launcher_path.read_text()
        installer = installer_path.read_text()
        self.assertIn("unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET TB_API_KEY",
                      launcher)
        self.assertIn("export ENABLE_DEMO_ORDERS=false", launcher)
        self.assertIn("export TRADEBOT_FIRE_DEMO_EXECUTION=false", launcher)
        self.assertIn("export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false", launcher)
        self.assertIn('export PYTHONPATH="$PROJECT/src"', launcher)
        self.assertIn('tradebot.offhost_alerts', launcher)
        self.assertIn("--check", installer)
        self.assertIn("sudo install -m 0644", installer)
        self.assertNotIn("sudo systemctl enable", installer)
        self.assertNotIn("sudo systemctl start", installer)
        self.assertNotIn("sudo systemctl restart", installer)

    def test_destinations_require_public_https_and_no_userinfo(self):
        for url in ("", "http://alerts.example.org/notify",
                    "https://localhost/x", "https://127.0.0.1/x",
                    "https://10.0.0.1/x", "https://metadata.google.internal/",
                    "https://alerts.example.org/#fragment",
                    "https://api-user:password@alerts.example.org/test",
                    "https://internal.local/h", "https://singlelabel/"):
            with self.subTest(url=url), self.assertRaises(AlertRelayError):
                validate_https_destination(url)
        self.assertEqual(validate_https_destination(self.webhook),
                         self.webhook)

    def test_exact_sanitized_payload_ack_cursor_and_replay_protection(self):
        self.healthy()
        self.events.publish(["missed_weekly_checkpoint"], at=self.now)
        calls = []

        def send(url, data=None, *, event_id=None):
            calls.append((url, json.loads(data) if data else None, event_id))

        result = deliver_once(self.root, self.webhook, self.ping,
                              send=send, now=self.now)
        self.assertEqual(result["events_acked"], 1)
        self.assertTrue(result["healthy_ping_acked"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], self.webhook)
        self.assertEqual(calls[0][1]["code"], "missed_weekly_checkpoint")
        self.assertEqual(calls[0][1]["environment"], "delta-india-demo")
        self.assertEqual(calls[0][1]["transition"], "opened")
        self.assertEqual(calls[0][2], 1)
        self.assertEqual(set(calls[0][1]), {
            "event", "environment", "id", "at_us", "code",
            "transition", "severity",
        })
        self.assertEqual(calls[1], (self.ping, None, None))
        self.assertEqual(self.fetch_cursor()[0], 1)
        calls.clear()

        again = deliver_once(self.root, self.webhook, self.ping,
                             send=send, now=self.now + timedelta(seconds=20))
        self.assertEqual(again["events_acked"], 0)
        self.assertFalse(again["healthy_ping_acked"])
        self.assertEqual(calls, [])

    def test_unacknowledged_webhook_retries_without_advancing_cursor(self):
        self.healthy()
        self.events.publish(["watchdog_restart_loop"], at=self.now)
        failed_calls = []

        def fail(url, data=None, *, event_id=None):
            failed_calls.append(event_id)
            raise AlertRelayError("external_delivery_unavailable")

        with self.assertRaisesRegex(AlertRelayError, "external_delivery_unavailable"):
            deliver_once(self.root, self.webhook, self.ping, send=fail, now=self.now)
        self.assertEqual(failed_calls, [1])
        self.assertEqual(self.fetch_cursor(), (0, 0))

        acked = []
        result = deliver_once(
            self.root, self.webhook, self.ping,
            send=lambda url, data=None, event_id=None:
                acked.append((url, event_id)),
            now=self.now,
        )
        self.assertEqual(result["events_acked"], 1)
        self.assertEqual(acked[0], (self.webhook, 1))

    def test_stale_watchdog_withholds_external_alive_ping(self):
        self.events.heartbeat("watchdog", at=self.now - timedelta(seconds=100))
        self.events.heartbeat("equity_collector", at=self.now)
        self.events.publish(["watchdog_heartbeat_stale"], at=self.now)
        calls = []

        report = deliver_once(
            self.root, self.webhook, self.ping,
            send=lambda url, data=None, event_id=None: calls.append(url),
            now=self.now,
        )
        self.assertEqual(report["events_acked"], 1)
        self.assertFalse(report["local_monitors_healthy"])
        self.assertFalse(report["healthy_ping_acked"])
        self.assertEqual(calls, [self.webhook])

    def test_no_alerts_still_allow_external_healthy_checkin(self):
        self.healthy()
        urls = []
        result = deliver_once(
            self.root, self.webhook, self.ping,
            send=lambda url, data=None, event_id=None: urls.append(url),
            now=self.now,
        )
        self.assertEqual(result["events_acked"], 0)
        self.assertTrue(result["healthy_ping_acked"])
        self.assertEqual(urls, [self.ping])

    def test_invalid_outbox_event_fails_closed_without_sending(self):
        with closing(sqlite3.connect(self.root / EVENT_DB)) as db:
            db.execute(
                "INSERT INTO monitor_events(at_us,code,transition,severity) "
                "VALUES (1234,'UNREDACTED_SECRET','opened','critical')"
            )
            db.commit()
        calls = []
        with self.assertRaisesRegex(AlertRelayError, "monitor_event_not_verified"):
            deliver_once(self.root, self.webhook, self.ping,
                         send=lambda *args, **kw: calls.append(args),
                         now=self.now)
        self.assertFalse(calls)

    def test_read_only_check_does_not_create_cursor_or_access_network(self):
        self.healthy()
        result = check_only(self.root, self.webhook, self.ping)
        self.assertEqual(result["status"],
                         "outbound_alerts_configured_not_commissioned")
        self.assertFalse(result["external_delivery_verified"])
        self.assertFalse(result["external_vm_loss_detection_verified"])
        self.assertFalse((self.root / CURSOR_DB).exists())

    def test_external_ping_failure_does_not_ack_healthy_heartbeat(self):
        self.healthy()

        def fail_ping(url, data=None, *, event_id=None):
            if url == self.ping:
                raise AlertRelayError("external_delivery_unavailable")

        with self.assertRaisesRegex(AlertRelayError, "external_delivery_unavailable"):
            deliver_once(self.root, self.webhook, self.ping,
                         send=fail_ping, now=self.now)
        self.assertEqual(self.fetch_cursor()[1], 0)

    def test_missing_monitor_outbox_is_never_created_from_scratch(self):
        uninitialized = self.root / "unknown"
        uninitialized.mkdir()
        with self.assertRaisesRegex(AlertRelayError, "monitor_outbox_unavailable"):
            deliver_once(uninitialized, self.webhook, self.ping,
                         send=lambda *a, **kw: None, now=self.now)
        self.assertFalse((uninitialized / EVENT_DB).exists())


if __name__ == "__main__":
    unittest.main()
