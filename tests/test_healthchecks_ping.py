"""Offline tests for Healthchecks.io VM-loss heartbeat; no actual HTTP calls."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import os
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tradebot.equity_monitor import MonitorStore
from tradebot.healthchecks_ping import (
    HeartbeatError, main, monitoring_preflight, run_once,
    send_ping, validate_ping_url,
)


PING = "https://hc-ping.com/01234567-89ab-cdef-0123-456789abcdef"


class HealthchecksPingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="healthchecks-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = MonitorStore(self.root / "fire-monitoring.sqlite")
        self.now = datetime.now(timezone.utc)

    def mark_healthy(self):
        for service in ("watchdog", "equity_collector"):
            self.db.start(service, at=self.now)
            self.db.heartbeat(service, at=self.now)

    def test_public_healthchecks_domain_and_one_or_two_segments_only(self):
        self.assertEqual(validate_ping_url(PING), PING)
        self.assertEqual(validate_ping_url(
            "https://hchk.io/example-123"), "https://hchk.io/example-123")
        for url in (
            "", "http://hc-ping.com/token", "https://localhost/token",
            "https://127.0.0.1/token", "https://metadata.google.internal/x",
            "https://hc-ping.com:444/token", "https://hc-ping.com/",
            "https://hc-ping.com/token/start/extra",
            "https://hc-ping.com/token?secret=abc",
            "https://hc-ping.com/token#fragment",
            "https://fixture-user:fixture-password@hc-ping.com/token",
            "https://hc-ping.com/%2e%2e/secrets",
            "https://hc-ping.com/token\nBad: 1",
        ):
            with self.subTest(url=url), self.assertRaises(HeartbeatError):
                validate_ping_url(url)

    def test_healthy_monitors_permit_only_one_outbound_ping(self):
        self.mark_healthy()
        sent = []
        report = run_once(self.root, PING, sender=sent.append)
        self.assertEqual(sent, [PING])
        self.assertEqual(report["status"],
                         "external_heartbeat_accepted_not_trade_authority")
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["broker_order_mutations"])

    def test_stale_watchdog_or_collector_deny_external_healthy_ping(self):
        for service in ("watchdog", "equity_collector"):
            self.mark_healthy()
            self.db.heartbeat(
                service, at=self.now - timedelta(minutes=5))
            called = []
            with self.assertRaisesRegex(HeartbeatError,
                                        "protective_monitor_unhealthy"):
                run_once(self.root, PING, sender=called.append)
            self.assertEqual(called, [])
            self.db.heartbeat(service, at=self.now)

    def test_future_heartbeat_denies_external_healthy_ping(self):
        self.mark_healthy()
        self.db.heartbeat("watchdog",
                          at=self.now + timedelta(minutes=10))
        with self.assertRaises(HeartbeatError):
            run_once(self.root, PING, sender=lambda _: self.fail("network"))

    def test_missing_or_symlinked_original_monitor_db_is_never_created(self):
        missing = self.root / "new-dir"
        missing.mkdir()
        with self.assertRaisesRegex(HeartbeatError,
                                    "monitor_evidence_unavailable"):
            run_once(missing, PING, sender=lambda _: self.fail("network"))
        self.assertFalse((missing / "fire-monitoring.sqlite").exists())
        alias = self.root / "alias"
        alias.mkdir()
        (alias / "fire-monitoring.sqlite").symlink_to(self.db.path)
        with self.assertRaises(HeartbeatError):
            monitoring_preflight(alias)

    def test_ping_http_requires_200_and_ok_without_exposing_url(self):
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *unused): return False
            def read(self, count): return b"OK"
        class FakeOpener:
            def open(self, req, timeout):
                self.request, self.timeout = req, timeout
                return FakeResponse()

        fake = FakeOpener()
        with mock.patch("tradebot.healthchecks_ping.request.build_opener",
                        return_value=fake):
            send_ping(PING)
        self.assertEqual(fake.request.get_method(), "GET")
        self.assertEqual(fake.timeout, 8)
        self.assertEqual(fake.request.full_url, PING)

        class BadResponse(FakeResponse):
            status = 500
        class BadOpener(FakeOpener):
            def open(self, req, timeout): return BadResponse()
        with mock.patch("tradebot.healthchecks_ping.request.build_opener",
                        return_value=BadOpener()):
            with self.assertRaisesRegex(HeartbeatError,
                                        "healthchecks_ack_unverified"):
                send_ping(PING)

    def test_failed_delivery_never_falsely_reports_success(self):
        self.mark_healthy()
        with self.assertRaisesRegex(HeartbeatError,
                                    "healthchecks_delivery_unavailable"):
            run_once(self.root, PING, sender=lambda _: 1 / 0)

    def test_check_mode_is_no_network_and_does_not_modify_monitoring(self):
        self.mark_healthy()
        before = self.db.path.stat().st_mtime_ns
        capture = io.StringIO()
        with mock.patch.dict(os.environ, {
                "TRADEBOT_EXTERNAL_HEARTBEAT_URL": PING}):
            with mock.patch(
                    "tradebot.healthchecks_ping.send_ping",
                    side_effect=AssertionError("network forbidden")):
                with redirect_stdout(capture):
                    code = main(["--data-dir", str(self.root), "--check"])
        self.assertEqual(code, 0)
        self.assertEqual(before, self.db.path.stat().st_mtime_ns)
        report = json.loads(capture.getvalue())
        self.assertEqual(report["status"],
                         "healthchecks_ready_for_supervised_ping")
        self.assertNotIn(PING, capture.getvalue())

    def test_cli_errors_are_sanitized_and_never_echo_secret_url(self):
        capture = io.StringIO()
        with mock.patch.dict(os.environ, {
                "TRADEBOT_EXTERNAL_HEARTBEAT_URL": PING}):
            with redirect_stdout(capture):
                code = main(["--data-dir", str(self.root), "--ping"])
        self.assertEqual(code, 2)
        self.assertNotIn(PING, capture.getvalue())
        self.assertEqual(json.loads(capture.getvalue())["trade_authorized"],
                         False)

    def test_shell_guards_and_stage_only_installer(self):
        project = Path(__file__).resolve().parents[1]
        paths = [
            project / "ops/run_healthchecks_ping.sh",
            project / "ops/install_healthchecks_ping_timer.sh",
        ]
        for p in paths:
            with self.subTest(p=p):
                process = subprocess.run(
                    ["bash", "-n", str(p)], capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stderr)
        runner = paths[0].read_text()
        installer = paths[1].read_text()
        self.assertIn('source "$CONFIG"', runner)
        self.assertIn('export PYTHONPATH="$PROJECT/src"', runner)
        self.assertLess(runner.index('source "$CONFIG"'),
                        runner.index('export PYTHONPATH="$PROJECT/src"'))
        self.assertIn("unset DELTA_DEMO_API_KEY DELTA_DEMO_API_SECRET TB_API_KEY",
                      runner)
        self.assertIn("export ENABLE_DEMO_ORDERS=false", runner)
        self.assertIn("export TRADEBOT_FIRE_DEMO_EXECUTION=false", runner)
        self.assertIn("export TRADEBOT_GOLD_FIRE_DEMO_EXECUTION=false", runner)
        self.assertIn("tradebot.healthchecks_ping", runner)
        self.assertIn("--check", installer)
        self.assertIn("OnUnitInactiveSec=60s", installer)
        self.assertIn("OnActiveSec=20s", installer)
        self.assertIn("sudo systemctl daemon-reload", installer)
        self.assertNotIn("sudo systemctl restart", installer)
        self.assertNotIn("sudo systemctl enable", installer)
        self.assertNotIn("sudo systemctl start", installer)


if __name__ == "__main__":
    unittest.main()
